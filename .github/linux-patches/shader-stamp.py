#!/usr/bin/env python3
"""Keeps Fritchii's "Preparing shaders" stamp check (CMakeModules/Nx2ShaderStamp.cmake, v6.2+)
working with Tuxchii's Linux patches.

Fritchii stamps prepared shaders with a hash of the shader translator's sources, and its build
stops when that hash isn't a stamp Frizti released. Tuxchii patches some of those sources on
purpose (radv-mesh-sgpr-workaround.patch), so its hash is never one of his. Instead of turning the
check off, this gives Tuxchii its own stamp, derived from the stamp of Frizti's source for the
same version plus what our patches change in those files:

- Tuxchii players prepare again when the shader sources in Frizti's tag change, or when our
  shader-affecting patch lines change; not on every rebase or unrelated edit.
- It is registered the way Frizti registers his: KnownStamps gets the Tuxchii stamp, and
  SameAsReleased maps this build's hash to it.

Usage, from the source root:
  shader-stamp.py upstream <state-file>             before any Linux patch: the upstream stamp
  shader-stamp.py register <state-file> <patch>...  after all patches and branding
"""
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import tempfile

MODULE = "CMakeModules/Nx2ShaderStamp.cmake"
LISTS = "src/video_core/CMakeLists.txt"


def stamp_inputs(root):
    """The files NX2_SHADER_STAMP_INPUTS globs, as CMake would (absolute paths)."""
    text = open(os.path.join(root, LISTS)).read()
    m = re.search(r"file\(GLOB_RECURSE NX2_SHADER_STAMP_INPUTS CONFIGURE_DEPENDS(.*?)\)", text, re.S)
    if not m:
        sys.exit(f"::error::{LISTS}: NX2_SHADER_STAMP_INPUTS not found")
    files = set()
    for pat in re.findall(r'"([^"]+)"', m.group(1)):
        pat = (pat.replace("${PROJECT_SOURCE_DIR}", root)
                  .replace("${CMAKE_CURRENT_SOURCE_DIR}", os.path.join(root, "src/video_core")))
        base, name = os.path.split(pat)
        for d, _, fs in os.walk(base):
            files.update(os.path.join(d, f) for f in fs if fnmatch.fnmatchcase(f, name))
    return sorted(files)


def run_module(root, any_stamp):
    """Runs Fritchii's own script; returns (stamp, error text)."""
    with tempfile.TemporaryDirectory() as tmp:
        lst, out = os.path.join(tmp, "inputs.txt"), os.path.join(tmp, "stamp.h")
        open(lst, "w").write("\n".join(stamp_inputs(root)) + "\n")
        env = dict(os.environ)
        env.pop("FRITCHII_SHADER_STAMP_ANY", None)
        if any_stamp:
            env["FRITCHII_SHADER_STAMP_ANY"] = "1"
        r = subprocess.run(["cmake", f"-DINPUT_LIST={lst}", f"-DOUT={out}", "-P",
                            os.path.join(root, MODULE)], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stdout + r.stderr
        return re.search(r'NX2_SHADER_STAMP "([0-9a-f]+)"', open(out).read()).group(1), ""


def known_stamps(root):
    m = re.search(r'set\(KnownStamps "([^"]*)"\)', open(os.path.join(root, MODULE)).read())
    return m.group(1).split(";") if m else []


def patch_shader_lines(patches, root):
    """The +/- lines our patches make in stamp input files (not context or line numbers)."""
    inputs = {os.path.relpath(p, root) for p in stamp_inputs(root)}
    lines, current = [], None
    for p in patches:
        for line in open(p, encoding="utf-8", errors="replace"):
            if line.startswith("+++ "):
                current = line[4:].strip()
                current = current[2:] if current.startswith("b/") else current
            elif line.startswith("--- ") or line.startswith("diff "):
                continue
            elif current in inputs and line[:1] in "+-":
                lines.append(f"{current}:{line.rstrip()}")
    return lines


def main():
    root = os.getcwd()
    if not os.path.exists(os.path.join(root, MODULE)):
        print("no Preparing shaders stamp check in this version: nothing to do")
        return
    mode, state = sys.argv[1], sys.argv[2]
    if mode == "upstream":
        stamp, err = run_module(root, any_stamp=False)
        if stamp is None:
            # The public tag doesn't hash to one of Frizti's released stamps (seen with v6.2: his
            # public tags are trimmed snapshots of what he builds). Use the tag's own hash: the
            # Tuxchii stamp then changes whenever the tag's shader sources do.
            stamp, err2 = run_module(root, any_stamp=True)
            if stamp is None:
                sys.exit(f"::error::Nx2ShaderStamp.cmake failed on the upstream source:\n{err2}")
            print(f"note: the upstream tag hashes to {stamp}, not one of Frizti's released stamps "
                  f"{known_stamps(root)}; using it as is")
        open(state, "w").write(stamp + "\n")
        print(f"upstream Preparing shaders stamp: {stamp}")
        return
    if mode != "register":
        sys.exit(__doc__)
    upstream = open(state).read().strip()
    raw, _ = run_module(root, any_stamp=True)
    if raw in known_stamps(root):
        print(f"stamp {raw} is already a released one: nothing to register")
        return
    lines = patch_shader_lines(sys.argv[3:], root)
    ours = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    tux = hashlib.sha256(f"tuxchii;{upstream};{ours}".encode()).hexdigest()[:16]
    text = open(os.path.join(root, MODULE)).read()
    text, n1 = re.subn(r'set\(KnownStamps "([^"]*)"\)',
                       lambda m: f'set(KnownStamps "{m.group(1)};{tux}")', text, count=1)
    text, n2 = re.subn(r'set\(SameAsReleased "([^"]*)"\)',
                       lambda m: f'set(SameAsReleased "{raw}={tux};{m.group(1)}")', text, count=1)
    if n1 != 1 or n2 != 1:
        sys.exit(f"::error::{MODULE}: KnownStamps or SameAsReleased not found")
    open(os.path.join(root, MODULE), "w").write(text)
    check, err = run_module(root, any_stamp=False)
    if check != tux:
        sys.exit(f"::error::Tuxchii stamp {tux} did not register (got {check}):\n{err}")
    print(f"Tuxchii Preparing shaders stamp: {tux} (from Frizti's {upstream} and "
          f"{len(lines)} shader lines in our patches; this build hashes to {raw})")


if __name__ == "__main__":
    main()
