import copy
import inspect
import typing
from pathlib import Path

import pytest
# First thing we need to do is set up the config loader (before importing anything else!)
# We can"t do from pycheribuild.configloader import ConfigLoader here because that will only update the local copy
from pycheribuild.targets import target_manager
# noinspection PyUnresolvedReferences
# make sure all projects are loaded so that target_manager gets populated
from pycheribuild.projects import *  # noqa: F401, F403
from pycheribuild.projects.cross import *  # noqa: F401, F403
from .setup_mock_chericonfig import setup_mock_chericonfig

global_config = setup_mock_chericonfig(Path("/this/path/does/not/exist"))


# noinspection PyProtectedMember
def _sort_targets(targets: "typing.List[str]", add_dependencies=False, add_toolchain=True,
                  skip_sdk=False, build_morello_from_source=False) -> "typing.List[str]":
    target_manager.reset()
    # print(real_targets)
    real_targets = list(target_manager.get_target(t, None, global_config, caller="_sort_targets") for t in targets)
    global_config.include_dependencies = add_dependencies
    global_config.include_toolchain_dependencies = add_toolchain
    global_config.skip_sdk = skip_sdk
    global_config.build_morello_firmware_from_source = build_morello_from_source
    for t in real_targets:
        if t.project_class._xtarget is None:
            continue
    for t in target_manager.targets:
        assert t.project_class._cached_full_deps is None
        assert t.project_class._cached_filtered_deps is None
    result = list(t.name for t in target_manager.get_all_targets(real_targets, global_config))
    # print("result = ", result)
    return result


freestanding_deps = ["llvm-native", "qemu", "gdb-native", "freestanding-sdk"]
baremetal_deps = freestanding_deps + ["newlib-baremetal-mips64", "compiler-rt-builtins-baremetal-mips64",
                                      "libunwind-baremetal-mips64", "libcxxrt-baremetal-mips64",
                                      "libcxx-baremetal-mips64", "baremetal-sdk"]
cheribsd_sdk_deps = freestanding_deps + ["cheribsd-mips64-hybrid", "cheribsd-sdk-mips64-hybrid"]


@pytest.mark.parametrize("target_name,expected_list", [
    pytest.param("freestanding-sdk", freestanding_deps, id="freestanding-sdk"),
    pytest.param("baremetal-sdk", baremetal_deps, id="baremetal-sdk"),
    # Ensure that cheribsd is added to deps even on Linux/Mac
    pytest.param("cheribsd-sdk-mips64-hybrid", cheribsd_sdk_deps, id="cheribsd-sdk"),
    pytest.param("sdk-mips64-hybrid", cheribsd_sdk_deps + ["sdk-mips64-hybrid"], id="sdk"),
    ])
def test_sdk(target_name, expected_list):
    assert _sort_targets([target_name]) == expected_list


@pytest.mark.parametrize("target_name,expected_name", [
    pytest.param("disk-image-fett", "disk-image-fett-riscv64-purecap"),
    pytest.param("llvm", "llvm-native"),
    pytest.param("gdb", "gdb-native"),
    ])
def test_alias_resolving(target_name, expected_name):
    # test that we select the default target for multi projects:
    assert _sort_targets([target_name]) == [expected_name]


def test_reordering():
    # GDB is a cross compiled project so cheribsd should be built first
    assert _sort_targets(["cheribsd-mips64-hybrid", "gdb-mips64-hybrid"]) == ["cheribsd-mips64-hybrid",
                                                                              "gdb-mips64-hybrid"]
    assert _sort_targets(["gdb-mips64-hybrid", "cheribsd-mips64-hybrid"]) == ["cheribsd-mips64-hybrid",
                                                                              "gdb-mips64-hybrid"]
    assert _sort_targets(["gdb-mips64-hybrid", "cheribsd-cheri"]) == ["cheribsd-mips64-hybrid", "gdb-mips64-hybrid"]


def test_run_comes_last():
    assert _sort_targets(["run-mips64-hybrid", "disk-image-mips64-hybrid"]) == [
        "disk-image-mips64-hybrid", "run-mips64-hybrid"]


def test_disk_image_comes_second_last():
    assert _sort_targets(["run-mips64-hybrid", "disk-image-mips64-hybrid"]) == ["disk-image-mips64-hybrid",
                                                                                "run-mips64-hybrid"]
    assert _sort_targets(["run-mips64-hybrid", "disk-image-mips64-hybrid", "cheribsd-mips64-hybrid"]) == [
        "cheribsd-mips64-hybrid", "disk-image-mips64-hybrid", "run-mips64-hybrid"]
    assert _sort_targets(
        ["run-mips64-hybrid", "gdb-mips64-hybrid", "disk-image-mips64-hybrid", "cheribsd-mips64-hybrid"]) == [
               "cheribsd-mips64-hybrid", "gdb-mips64-hybrid", "disk-image-mips64-hybrid", "run-mips64-hybrid"]
    assert _sort_targets(
        ["run-mips64-hybrid", "disk-image-mips64-hybrid", "postgres-mips64-hybrid", "cheribsd-mips64-hybrid"]) == [
               "cheribsd-mips64-hybrid", "postgres-mips64-hybrid", "disk-image-mips64-hybrid", "run-mips64-hybrid"]


def test_cheribsd_default_aliases():
    assert _sort_targets(["run-mips64-hybrid"]) == ["run-mips64-hybrid"]
    assert _sort_targets(["disk-image-mips64-hybrid"]) == ["disk-image-mips64-hybrid"]
    assert _sort_targets(["cheribsd-mips64-hybrid"]) == ["cheribsd-mips64-hybrid"]


def test_all_run_deps():
    assert _sort_targets(["run-mips64-hybrid"], add_dependencies=True) == [
        "qemu", "llvm-native", "cheribsd-mips64-hybrid", "gdb-mips64-hybrid", "disk-image-mips64-hybrid",
        "run-mips64-hybrid"]


def test_run_disk_image():
    assert _sort_targets(["run-mips64-hybrid", "disk-image-mips64-hybrid", "run-freebsd-mips64", "llvm",
                          "disk-image-freebsd-amd64"]) == [
               "llvm-native", "disk-image-mips64-hybrid", "disk-image-freebsd-amd64", "run-mips64-hybrid",
               "run-freebsd-mips64"]


def test_remove_duplicates():
    assert _sort_targets(["binutils", "llvm"], add_dependencies=True) == ["llvm-native"]


def test_minimal_run():
    # Check that we build the mfs root first
    assert _sort_targets(["disk-image-minimal-mips64-hybrid",
                          "cheribsd-mfs-root-kernel-mips64-hybrid",
                          "run-minimal-mips64-hybrid"]) == ["disk-image-minimal-mips64-hybrid",
                                                            "cheribsd-mfs-root-kernel-mips64-hybrid",
                                                            "run-minimal-mips64-hybrid"]
    assert _sort_targets(["cheribsd-mfs-root-kernel-mips64-hybrid", "disk-image-minimal-mips64-hybrid",
                          "run-minimal-mips64-hybrid"]) == ["disk-image-minimal-mips64-hybrid",
                                                            "cheribsd-mfs-root-kernel-mips64-hybrid",
                                                            "run-minimal-mips64-hybrid"]


def _check_deps_not_cached(classes):
    for c in classes:
        with pytest.raises(ValueError, match="cached_full_dependencies called before value was cached"):
            # noinspection PyProtectedMember
            c.cached_full_dependencies()


def _check_deps_cached(classes):
    for c in classes:
        # noinspection PyProtectedMember
        assert len(c.cached_full_dependencies()) > 0


def test_webkit_cached_deps():
    # regression test for a bug in caching deps
    config = copy.copy(global_config)
    config.skip_sdk = True
    config.include_toolchain_dependencies = False
    config.include_dependencies = True
    webkit_native = target_manager.get_target_raw("qtwebkit-native").project_class
    webkit_cheri = target_manager.get_target_raw("qtwebkit-mips64-purecap").project_class
    webkit_mips = target_manager.get_target_raw("qtwebkit-mips64-hybrid").project_class
    # Check that the deps are not cached yet
    _check_deps_not_cached((webkit_native, webkit_cheri, webkit_mips))
    assert inspect.getattr_static(webkit_native, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]
    assert inspect.getattr_static(webkit_cheri, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]
    assert inspect.getattr_static(webkit_mips, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]

    cheri_target_names = list(sorted(webkit_cheri.all_dependency_names(config)))
    assert cheri_target_names == ["cheribsd-mips64-purecap", "icu4c-mips64-purecap", "icu4c-native",
                                  "libxml2-mips64-purecap", "llvm-native", "qtbase-mips64-purecap",
                                  "sqlite-mips64-purecap"]
    _check_deps_not_cached([webkit_native, webkit_mips])
    _check_deps_cached([webkit_cheri])
    mips_target_names = list(sorted(webkit_mips.all_dependency_names(config)))
    assert mips_target_names == ["cheribsd-mips64-hybrid", "icu4c-mips64-hybrid", "icu4c-native",
                                 "libxml2-mips64-hybrid", "llvm-native", "qtbase-mips64-hybrid", "sqlite-mips64-hybrid"]
    _check_deps_cached([webkit_cheri, webkit_mips])
    _check_deps_not_cached([webkit_native])

    native_target_names = list(sorted(webkit_native.all_dependency_names(config)))
    assert native_target_names == ["icu4c-native", "libxml2-native", "qtbase-native", "sqlite-native"]
    _check_deps_cached([webkit_cheri, webkit_mips, webkit_native])
    assert inspect.getattr_static(webkit_native, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]
    assert inspect.getattr_static(webkit_cheri, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]
    assert inspect.getattr_static(webkit_mips, "dependencies") == ["qtbase", "icu4c", "libxml2", "sqlite"]


def test_webkit_deps_2():
    # SDK should not add new targets
    assert _sort_targets(["qtwebkit-native"], add_dependencies=True, skip_sdk=False) == [
        "qtbase-native", "icu4c-native", "libxml2-native", "sqlite-native", "qtwebkit-native"]
    assert _sort_targets(["qtwebkit-native"], add_dependencies=True, skip_sdk=True) == [
        "qtbase-native", "icu4c-native", "libxml2-native", "sqlite-native", "qtwebkit-native"]

    assert _sort_targets(["qtwebkit-mips64-hybrid"], add_dependencies=True, skip_sdk=True) == [
        "qtbase-mips64-hybrid", "icu4c-native", "icu4c-mips64-hybrid", "libxml2-mips64-hybrid", "sqlite-mips64-hybrid",
        "qtwebkit-mips64-hybrid"]
    assert _sort_targets(["qtwebkit-mips64-purecap"], add_dependencies=True, skip_sdk=True) == [
        "qtbase-mips64-purecap", "icu4c-native", "icu4c-mips64-purecap", "libxml2-mips64-purecap",
        "sqlite-mips64-purecap", "qtwebkit-mips64-purecap"]


def test_riscv():
    assert _sort_targets(["bbl-baremetal-riscv64", "cheribsd-riscv64"], add_dependencies=False, skip_sdk=False) == [
        "bbl-baremetal-riscv64", "cheribsd-riscv64"]
    assert _sort_targets(["run-riscv64"], add_dependencies=True, skip_sdk=True) == ["disk-image-riscv64", "run-riscv64"]
    assert _sort_targets(["run-riscv64-purecap"], add_dependencies=True, skip_sdk=True) == [
        "bbl-baremetal-riscv64-purecap", "disk-image-riscv64-purecap", "run-riscv64-purecap"]
    assert _sort_targets(["disk-image-riscv64"], add_dependencies=True, skip_sdk=False) == [
        "llvm-native", "cheribsd-riscv64", "gdb-riscv64", "disk-image-riscv64"]
    assert _sort_targets(["run-riscv64"], add_dependencies=True, skip_sdk=False) == [
        "qemu", "llvm-native", "cheribsd-riscv64", "gdb-riscv64", "disk-image-riscv64", "run-riscv64"]


# Check that libcxx deps with skip sdk pick the matching -native/-mips versions
# Also the libcxx target should resolve to libcxx-mips-purecap:
@pytest.mark.parametrize("suffix,expected_suffix", [
    pytest.param("-native", "-native", id="native"),
    pytest.param("-mips64", "-mips64", id="mips-nocheri"),
    pytest.param("-mips64-hybrid", "-mips64-hybrid", id="mips64-hybrid"),
    pytest.param("-mips64-purecap", "-mips64-purecap", id="mips64-purecap"),
    # legacy suffixes
    pytest.param("-mips-nocheri", "-mips64", id="mips-nocheri"),
    pytest.param("-mips64-hybrid", "-mips64-hybrid", id="mips-hybrid"),
    pytest.param("-mips-purecap", "-mips64-purecap", id="mips-purecap"),
    ])
def test_libcxx_deps(suffix, expected_suffix):
    expected = ["libunwind" + expected_suffix, "libcxxrt" + expected_suffix, "libcxx" + expected_suffix]
    # Now check that the cross-compile versions explicitly chose the matching target:
    assert expected == _sort_targets(["libcxx" + suffix], add_dependencies=True, skip_sdk=True)


@pytest.mark.parametrize("target_name,include_recursive_deps,include_toolchain,expected_deps,morello_from_source", [
    pytest.param("morello-firmware", False, False,
                 ["morello-scp-firmware", "morello-trusted-firmware",
                  "morello-flash-images", "morello-uefi", "morello-firmware"], True,
                 id="firmware from source (no deps)"),
    pytest.param("morello-firmware", True, True,
                 ["morello-scp-firmware", "morello-trusted-firmware",
                  "morello-flash-images", "morello-uefi", "morello-firmware"], True,
                 id="firmware from source (deps)"),
    pytest.param("morello-firmware", True, True, ["morello-firmware"], False,
                 id="firmware dowload (deps)"),
    pytest.param("morello-firmware", False, False, ["morello-firmware"], False,
                 id="firmware dowload (no deps)"),
    pytest.param("morello-uefi", False, False, ["morello-uefi"], True),
    pytest.param("morello-uefi", False, True, ["morello-uefi"], True),
    pytest.param("morello-uefi", True, False, ["morello-uefi"], True),
    pytest.param("morello-uefi", True, True, ["gdb-native", "morello-acpica", "morello-llvm", "morello-uefi"], True),
    ])
def test_skip_toolchain_deps(target_name, include_recursive_deps, include_toolchain, expected_deps,
                             morello_from_source):
    # Check that morello-firmware does not include toolchain dependencies by default, but the individual ones does
    # TODO: should we do the same for all-<target>?
    assert _sort_targets([target_name], add_dependencies=include_recursive_deps, add_toolchain=include_toolchain,
                         build_morello_from_source=morello_from_source) == expected_deps
