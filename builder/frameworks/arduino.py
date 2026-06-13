# Copyright 2026-present zackees
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Arduino framework binding for NXP LPC8xx (Cortex-M0+).

Wires the ArduinoCore-LPC8xx package (`framework-arduino-lpc8xx`) into
PlatformIO/SCons:

  - Locates the framework package and its `cores/<core>/` + `variants/<variant>/`
    layout (Arduino 1.5+ hardware-package convention).
  - Mirrors the compile / link flags from upstream platform.txt:
      compiler.cpp.flags  -> CCFLAGS + CXXFLAGS
      compiler.c.elf.flags -> LINKFLAGS
  - Adds the standard Arduino defines (ARDUINO, ARDUINO_ARCH_LPC8XX,
    ARDUINO_<BOARD>, F_CPU) plus board-level extras from
    `boards/<id>.json` -> build.extra_flags (e.g., -DCPU_LPC845M301JBD48).
  - Picks the linker script: `board_build.ldscript` override if present,
    else the framework's per-MCU default (so none need be specified).
  - Builds two static libs (variant + core) and prepends them to LIBS so
    they win over any same-named symbols from user code.
"""

import os

from SCons.Script import DefaultEnvironment

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

FRAMEWORK_DIR = platform.get_package_dir("framework-arduino-lpc8xx")
assert FRAMEWORK_DIR and os.path.isdir(FRAMEWORK_DIR), (
    "framework-arduino-lpc8xx package not installed; expected at %r" %
    FRAMEWORK_DIR)

CORE = board.get("build.core", "lpc8xx")
VARIANT = board.get("build.variant")
assert VARIANT, (
    "build.variant must be set in boards/<id>.json for LPC8xx Arduino "
    "builds (was empty for board %s)" % board.id)

CORE_DIR = os.path.join(FRAMEWORK_DIR, "cores", CORE)
VARIANT_DIR = os.path.join(FRAMEWORK_DIR, "variants", VARIANT)
LIBRARIES_DIR = os.path.join(FRAMEWORK_DIR, "libraries")

assert os.path.isdir(CORE_DIR), (
    "Arduino core directory missing: %s" % CORE_DIR)
assert os.path.isdir(VARIANT_DIR), (
    "Arduino variant directory missing: %s" % VARIANT_DIR)


machine_flags = [
    "-mcpu=%s" % board.get("build.cpu"),
    "-mthumb",
]

# Compiler / linker flags mirror cores' platform.txt so behavior matches
# the arduino-cli compile path used by the package's own CI.
env.Append(
    ASFLAGS=machine_flags,
    ASPPFLAGS=["-x", "assembler-with-cpp"],

    CFLAGS=[
        "-std=gnu11",
    ],

    CCFLAGS=machine_flags + [
        "-Os",
        "-Wall",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-common",
        "-MMD",
    ],

    CXXFLAGS=[
        "-std=gnu++11",
        "-fno-rtti",
        "-fno-exceptions",
        "-fno-threadsafe-statics",
        "-fno-use-cxa-atexit",
    ],

    CPPDEFINES=[
        ("ARDUINO", 10819),
        "ARDUINO_ARCH_LPC8XX",
        ("F_CPU", "$BOARD_F_CPU"),
    ],

    CPPPATH=[
        CORE_DIR,
        VARIANT_DIR,
    ],

    LINKFLAGS=machine_flags + [
        "-Os",
        "-Wl,--gc-sections",
        "--specs=nano.specs",
        "--specs=nosys.specs",
        "-Wl,--entry=Reset_Handler",
    ],

    LIBS=["c", "m", "gcc", "nosys"],
)

# `libraries/` ships with some Arduino cores; advertise it to PlatformIO's
# library dependency finder if present.
if os.path.isdir(LIBRARIES_DIR):
    env.Append(LIBSOURCE_DIRS=[LIBRARIES_DIR])

# Board-level extra flags (e.g., -DCPU_LPC845M301JBD48 -DLPC845
# -DARDUINO_LPC845BRK) come from boards/<id>.json -> build.extra_flags.
if board.get("build.extra_flags", ""):
    env.ProcessFlags(board.get("build.extra_flags"))

# Linker script. Resolution order:
#   1. An explicit `board_build.ldscript` (platformio.ini) or a `build.ldscript`
#      baked into the board JSON wins as-is.
#   2. Otherwise fall back to the framework's per-MCU default, so a stock board
#      links with no linker script specified anywhere by the user.
# The framework default is an absolute path under FRAMEWORK_DIR (resolves
# regardless of build CWD); its own root-relative `INCLUDE` directives are
# satisfied by the FRAMEWORK_DIR entry added to LIBPATH below.
FRAMEWORK_LDSCRIPTS = {
    "lpc845": "linker_scripts/gcc/lpc845_flash.ld",
    "lpc804": "linker_scripts/gcc/lpc804_flash.ld",
}
ldscript = board.get("build.ldscript", "")
if not ldscript:
    mcu = board.get("build.mcu", "").lower()
    default_ldscript = FRAMEWORK_LDSCRIPTS.get(mcu)
    assert default_ldscript, (
        "No default linker script for MCU %r; set board_build.ldscript in "
        "platformio.ini or add a FRAMEWORK_LDSCRIPTS entry." % mcu)
    ldscript = os.path.join(FRAMEWORK_DIR, default_ldscript)
env.Replace(LDSCRIPT_PATH=env.subst(ldscript))

# GNU ld resolves `INCLUDE <file>` directives against its -L search dirs and the
# CWD, not relative to the script that contains the INCLUDE. The framework
# linker scripts use framework-root-relative includes (e.g.
# `INCLUDE linker_scripts/gcc/lpc8xx_common.ld`), so the framework root must be
# on the linker search path for those scripts to link from any project dir.
env.Append(LIBPATH=[FRAMEWORK_DIR])

#
# Build variant + core as static libraries.
# Variant is prepended ahead of core so variant-specific symbols (pin maps,
# startup tweaks) override the core defaults during link.
#
libs = []
libs.append(env.BuildLibrary(
    os.path.join("$BUILD_DIR", "FrameworkArduinoVariant"),
    VARIANT_DIR,
))
libs.append(env.BuildLibrary(
    os.path.join("$BUILD_DIR", "FrameworkArduino"),
    CORE_DIR,
))
env.Prepend(LIBS=libs)
