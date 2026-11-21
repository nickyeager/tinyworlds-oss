"""Lightweight WASM browser-compatibility validator.

Catches the failure class where the build pipeline produces a syntactically
valid WASM file containing post-MVP value-type bytes (reference-types, GC,
typed-references) that mainstream browsers refuse to instantiate.

We don't fully decode the binary — we just walk sections, find the type
section, and assert every value-type byte in every signature is a member
of the "browser-safe" set. Anything else is flagged with offset + the
offending byte.

The safe set matches what current Chrome/Firefox/Safari enable by default
in `WebAssembly.instantiate`. Members of WASM proposals that are not
universally shipped (gc, reference-types, exceptions, typed-references)
are deliberately excluded — emit them, your game shows a black canvas.

References:
- WASM core spec value types: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64
- SIMD (universally shipped): 0x7B v128
- reference-types (universally shipped, but the *typed* forms below are not):
  0x70 funcref, 0x6F externref
- NOT safe: 0x6B `(ref null ht)`, 0x6C `(ref ht)`, 0x6E `anyref`,
  0x6D `eqref`, 0x69 `i31ref`, 0x68 `nullref`, etc.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


# Bytes that ALL current shipping browsers accept in a value-type position
# (parameter, result, local, global, table-element).
SAFE_VALUE_TYPES = frozenset(
    [
        0x7F,  # i32
        0x7E,  # i64
        0x7D,  # f32
        0x7C,  # f64
        0x7B,  # v128 (SIMD)
        0x70,  # funcref
        0x6F,  # externref
    ]
)


@dataclass
class WasmValidationIssue:
    offset: int
    byte: int
    detail: str

    def __str__(self) -> str:
        return f"byte 0x{self.byte:02X} at offset {self.offset}: {self.detail}"


class _Reader:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def u8(self) -> int:
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def leb128_u(self) -> int:
        """Unsigned LEB128. Most WASM length / index fields use this."""
        result = 0
        shift = 0
        while True:
            b = self.buf[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return result
            shift += 7

    def take(self, n: int) -> bytes:
        s = self.buf[self.pos : self.pos + n]
        self.pos += n
        return s


def _check_value_type(r: _Reader, issues: List[WasmValidationIssue]) -> None:
    """Read one value-type byte and flag it if it's outside the safe set."""
    offset = r.pos
    b = r.u8()
    if b not in SAFE_VALUE_TYPES:
        issues.append(
            WasmValidationIssue(
                offset=offset,
                byte=b,
                detail=_describe_unsafe_byte(b),
            )
        )


def _describe_unsafe_byte(b: int) -> str:
    # Best-effort names. Anything we don't recognize is "unknown post-MVP".
    known = {
        0x6B: "(ref null ht) — typed-references / GC proposal",
        0x6C: "(ref ht) — typed-references / GC proposal",
        0x6E: "anyref — GC proposal",
        0x6D: "eqref — GC proposal",
        0x69: "i31ref — GC proposal",
        0x68: "nullref — GC proposal",
        0x6A: "nullexternref — GC proposal",
        0x73: "nullfuncref — GC proposal",
    }
    if b in known:
        return f"{known[b]} — not enabled by default in shipping browsers"
    return "unknown post-MVP value type — not enabled by default in shipping browsers"


def validate_for_browser(wasm_bytes: bytes) -> List[WasmValidationIssue]:
    """Return a list of validation issues. Empty list = browser-safe.

    Only the type section is walked. Other sections may also contain
    instructions referencing the same heap types, but the type section is
    what V8 rejects first during `instantiateStreaming`, and a clean type
    section is a strong signal the whole binary is clean.
    """
    if len(wasm_bytes) < 8:
        return [WasmValidationIssue(0, 0, "file too small to be valid WASM")]

    # Magic + version
    if wasm_bytes[:4] != b"\x00asm":
        return [WasmValidationIssue(0, wasm_bytes[0], "missing \\0asm magic header")]
    if wasm_bytes[4:8] != b"\x01\x00\x00\x00":
        return [WasmValidationIssue(4, wasm_bytes[4], "unsupported WASM version")]

    issues: List[WasmValidationIssue] = []
    r = _Reader(wasm_bytes)
    r.pos = 8  # skip magic+version

    while r.pos < len(wasm_bytes):
        section_id = r.u8()
        section_size = r.leb128_u()
        section_end = r.pos + section_size

        if section_id == 1:  # Type section
            count = r.leb128_u()
            for _ in range(count):
                # Each entry is a function type: 0x60 then param-vec, result-vec.
                form_byte = r.u8()
                if form_byte != 0x60:
                    # Encountering 0x5E (array), 0x5F (struct) etc would mean
                    # the GC proposal is in use. Flag and stop the type walk.
                    issues.append(
                        WasmValidationIssue(
                            offset=r.pos - 1,
                            byte=form_byte,
                            detail=(
                                "type section entry is not a function type (0x60). "
                                "GC proposal struct/array types in use — not browser-safe."
                            ),
                        )
                    )
                    break

                param_count = r.leb128_u()
                for _ in range(param_count):
                    _check_value_type(r, issues)
                result_count = r.leb128_u()
                for _ in range(result_count):
                    _check_value_type(r, issues)

        # Skip to end of section regardless of what we did inside
        r.pos = section_end

    return issues


def validate_file(path: Path) -> List[WasmValidationIssue]:
    return validate_for_browser(path.read_bytes())
