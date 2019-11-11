#
# Copyright (c) 2019 Alfredo Mazzinghi
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory (Department of Computer Science and
# Technology) under DARPA contract HR0011-18-C-0016 ("ECATS"), as part of the
# DARPA SSITH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#

import shutil
import tempfile
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from .project import *
from .cross.crosscompileproject import *
from .cross.cheribsd import BuildCHERIBSDPurecap
from .build_qemu import BuildQEMU
from .disk_image import BuildCheriBSDPurecapDiskImage
from ..utils import *
from ..config.chericonfig import CrossCompileTarget
from ..config.loader import ComputedDefaultValue

class BuildSyzkaller(CrossCompileProject):
    dependencies = ["go", "cheribsd"]
    project_name = "cheri-syzkaller"
    githubBaseUrl = "https://github.com/CTSRD-CHERI/"
    repository = GitRepository(githubBaseUrl + "cheri-syzkaller.git")
    # no_default_sysroot = None // probably useless??
    appendCheriBitsToBuildDir = True
    # skip_cheri_symlinks = True // llvm target only, useless here
    make_kind = MakeCommandKind.GnuMake

    # is_sdk_target = True
    # _mips_build_hybrid = True
    supported_architectures = [CrossCompileTarget.CHERIBSD_MIPS]

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.sysgen = cls.addBoolOption(
            "run-sysgen", showHelp=True,
            help="Rerun syz-extract and syz-sysgen to rebuild generated Go "
            "syscall descriptions.")

    def __init__(self, config):
        super().__init__(config)

        # self.gopath = source_base / gohome
        self.goroot = config.sdkDir / "go"

        repo_url = urlparse(self.repository.url)
        repo_path = repo_url.path.split(".")[0]
        parts = ["src", repo_url.netloc] + repo_path.split("/")
        self.gopath = self.buildDir
        self.gosrc = self.sourceDir

        self.rootfs = config.outputRoot / ("rootfs" + config.cheri_bits_and_abi_str)
        self.cheribsd_include = self.rootfs / "usr" / "include"

        self._newPath = (str(self.config.sdkDir.expanduser() / "bin") + ":" +
                         str(self.config.dollarPathWithOtherTools))

        self.cheribsd_dir = self.config.sourceRoot / "cheribsd"

    def syzkaller_install_path(self):
        return self.config.sdkDir / "bin"

    def syzkaller_binary(self):
        return self.config.sdkDir / "bin" / "syz-manager"

    def needsConfigure(self) -> bool:
        return False

    def compile(self, **kwargs):
        cflags = self.default_compiler_flags + self.default_ldflags

        self.make_args.set_env(
            HOSTARCH="amd64",
            TARGETARCH="mips64",
            GOROOT=self.goroot.expanduser(),
            GOPATH=self.gopath.expanduser(),
            CC=self.config.sdkBinDir.expanduser() / "clang",
            CXX=self.config.sdkBinDir.expanduser() / "clang++")
        if self.sysgen:
            self.generate()

        self.make_args.set_env(CFLAGS=" ".join(cflags))
        with setEnv(PATH=self._newPath):
            self.runMake(parallel=False, cwd=self.gosrc)

    def generate(self, **kwargs):
        with setEnv(PATH=self._newPath, SOURCEDIR=self.cheribsd_dir):
            self.runMake("extract", parallel=False, cwd=self.gosrc)
            self.runMake("generate", parallel=False, cwd=self.gosrc)

    def install(self, **kwargs):
        # XXX-AM: should have a propert install dir configuration
        native_build = self.sourceDir / "bin"
        mips64_build = native_build / "freebsd_mips64"
        syz_remote_install = self.syzkaller_install_path() / "freebsd_mips64"

        self.makedirs(syz_remote_install)

        self.installFile(native_build / "syz-manager", self.syzkaller_binary(), mode=0o755)

        if not self.config.pretend:
            # mips64_build does not exist if we preted, so skip
            for fname in os.listdir(str(mips64_build)):
                fpath = mips64_build / fname
                if os.path.isfile(fpath):
                    self.installFile(fpath, syz_remote_install / fname, mode=0o755)

    def clean(self) -> ThreadJoiner:
        assert self.config.clean
        self._git_clean_source_dir()


class RunSyzkaller(SimpleProject):
    project_name = "run-syzkaller"

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.syz_config = cls.addPathOption("syz-config", default=None,
                                           help="Path to the syzkaller configuration file to use.",
                                           showHelp=True)
        cls.syz_ssh_key = cls.addPathOption("ssh-privkey", showHelp=True,
            default=lambda config, project: (config.sourceRoot / "extra-files" / "syzkaller_id_rsa"),
            help="A directory with additional files that will be added to the image (default: "
                 "'$SOURCE_ROOT/extra-files/syzkaller_id_rsa')", metavar="syzkaller_id_rsa")
        cls.syz_workdir = cls.addPathOption("workdir", showHelp=True,
            default=lambda config, project: (config.outputRoot / "syzkaller-workdir"),
            help="Working directory for syzkaller output.", metavar="DIR")

    def __init__(self, config: CheriConfig):
        super().__init__(config)

        self.qemu_binary = BuildQEMU.qemu_binary(self)
        self.syzkaller_binary = BuildSyzkaller.syzkaller_binary(self)
        self.kernel_path = BuildCHERIBSDPurecap.get_instance(
            None, config=config, cross_target=CrossCompileTarget.CHERIBSD_MIPS_PURECAP).get_installed_kernel_path(None, config=config)

        self.disk_image = BuildCheriBSDPurecapDiskImage.get_instance(
            self, config, cross_target=CrossCompileTarget.CHERIBSD_MIPS_PURECAP).diskImagePath

    def syzkaller_config(self):
        """ Get path of syzkaller configuration file to use. """
        if self.syz_config:
            return self.syz_config
        else:
            self.makedirs(self.syz_workdir)
            syz_config = self.syz_workdir / "syzkaller-config.json"

            template = {
                "name": "cheribsd-n64",
                "target": "freebsd/mips64",
                "http": ":10000",
                "workdir": str(self.syz_workdir),
                "syzkaller": str(BuildSyzkaller.syzkaller_install_path(self).parent),
                "sshkey": str(self.syz_ssh_key),
                "sandbox": "none",
                "procs": 1,
                "image": str(self.disk_image),
                "type": "qemu",
                "vm": {
	            "qemu": str(self.qemu_binary),
	            "qemu_args": "-M malta -device virtio-rng-pci -D syz-trace.log",
	            "kernel": str(self.kernel_path),
	            "image_device": "drive index=0,media=disk,format=raw,file=",
	            "count": 1,
	            "cpu": 1,
	            "mem": 2048,
	            "timeout": 60
                }
            }
            if not self.config.pretend:
                with open(syz_config, "w+") as fp:
                    print("Emit syzkaller configuration to {}".format(syz_config))
                    json.dump(template, fp, indent=4)

            return syz_config

    def process(self):
        syz_args = [self.syzkaller_binary, "-config", self.syzkaller_config()]
        if self.config.verbose:
            syz_args += ["-debug"]
        self.run_cmd(*syz_args)