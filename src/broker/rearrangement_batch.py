"""Provisional RearrangementBatchV1 wire layout for Phase 0A measurement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

PROTOCOL_VERSION = 1
N_MAX_MOVES = 1024
HEADER_WORDS = 16
MOVE_WORDS = 6
BATCH_WORDS = HEADER_WORDS + N_MAX_MOVES * MOVE_WORDS

OFF_PROTOCOL_VERSION = 0
OFF_SEQUENCE_NO = 1
OFF_N_MOVES = 2
OFF_DEADLINE_TICKS_LO = 3
OFF_DEADLINE_TICKS_MID = 4
OFF_DEADLINE_TICKS_HI = 5
OFF_SNAPSHOT_HASH_LO = 6
OFF_SNAPSHOT_HASH_MID = 7
OFF_SNAPSHOT_HASH_HI = 8
OFF_DESCRIPTOR_HASH_LO = 9
OFF_DESCRIPTOR_HASH_MID = 10
OFF_DESCRIPTOR_HASH_HI = 11
OFF_LOOP_INDEX = 12
OFF_MAX_LOOPS = 13
OFF_IDEAL_MOVES = 14
OFF_HEADER_FLAGS = 15

_MASK31 = 0x7FFF_FFFF


@dataclass(frozen=True)
class Move:
    src_x: int
    src_y: int
    tgt_x: int
    tgt_y: int
    group_id: int
    t_ramp_ticks: int
    flags: int


@dataclass(frozen=True)
class BatchHeader:
    protocol_version: int
    sequence_no: int
    n_moves: int
    deadline_ppu_ticks: int
    snapshot_hash64: int
    descriptor_hash64: int
    loop_index: int
    max_loops: int
    ideal_moves: int
    header_flags: int


def _split64(value: int) -> tuple[int, int, int]:
    value &= (1 << 64) - 1
    return value & _MASK31, (value >> 31) & _MASK31, (value >> 62) & _MASK31


def _join64(lo: int, mid: int, hi: int) -> int:
    return (hi << 62) | (mid << 31) | lo


def encode_batch(
    *,
    sequence_no: int,
    deadline_ppu_ticks: int,
    snapshot_hash64: int,
    descriptor_hash64: int,
    loop_index: int,
    max_loops: int,
    ideal_moves: int,
    moves: Sequence[Move],
) -> list[int]:
    if len(moves) > N_MAX_MOVES:
        raise ValueError(f"n_moves {len(moves)} exceeds N_MAX_MOVES {N_MAX_MOVES}")

    deadline_lo, deadline_mid, deadline_hi = _split64(deadline_ppu_ticks)
    snapshot_lo, snapshot_mid, snapshot_hi = _split64(snapshot_hash64)
    descriptor_lo, descriptor_mid, descriptor_hi = _split64(descriptor_hash64)
    words = [0] * BATCH_WORDS
    words[OFF_PROTOCOL_VERSION] = PROTOCOL_VERSION
    words[OFF_SEQUENCE_NO] = sequence_no & _MASK31
    words[OFF_N_MOVES] = len(moves)
    words[OFF_DEADLINE_TICKS_LO] = deadline_lo
    words[OFF_DEADLINE_TICKS_MID] = deadline_mid
    words[OFF_DEADLINE_TICKS_HI] = deadline_hi
    words[OFF_SNAPSHOT_HASH_LO] = snapshot_lo
    words[OFF_SNAPSHOT_HASH_MID] = snapshot_mid
    words[OFF_SNAPSHOT_HASH_HI] = snapshot_hi
    words[OFF_DESCRIPTOR_HASH_LO] = descriptor_lo
    words[OFF_DESCRIPTOR_HASH_MID] = descriptor_mid
    words[OFF_DESCRIPTOR_HASH_HI] = descriptor_hi
    words[OFF_LOOP_INDEX] = loop_index
    words[OFF_MAX_LOOPS] = max_loops
    words[OFF_IDEAL_MOVES] = ideal_moves
    words[OFF_HEADER_FLAGS] = 0

    for index, move in enumerate(moves):
        base = HEADER_WORDS + index * MOVE_WORDS
        words[base] = move.src_x
        words[base + 1] = move.src_y
        words[base + 2] = move.tgt_x
        words[base + 3] = move.tgt_y
        words[base + 4] = move.group_id
        words[base + 5] = ((move.flags & 0xFFFF) << 16) | (move.t_ramp_ticks & 0xFFFF)
    return words


def decode_header(words: Sequence[int]) -> BatchHeader:
    return BatchHeader(
        protocol_version=words[OFF_PROTOCOL_VERSION],
        sequence_no=words[OFF_SEQUENCE_NO],
        n_moves=words[OFF_N_MOVES],
        deadline_ppu_ticks=_join64(
            words[OFF_DEADLINE_TICKS_LO],
            words[OFF_DEADLINE_TICKS_MID],
            words[OFF_DEADLINE_TICKS_HI],
        ),
        snapshot_hash64=_join64(
            words[OFF_SNAPSHOT_HASH_LO],
            words[OFF_SNAPSHOT_HASH_MID],
            words[OFF_SNAPSHOT_HASH_HI],
        ),
        descriptor_hash64=_join64(
            words[OFF_DESCRIPTOR_HASH_LO],
            words[OFF_DESCRIPTOR_HASH_MID],
            words[OFF_DESCRIPTOR_HASH_HI],
        ),
        loop_index=words[OFF_LOOP_INDEX],
        max_loops=words[OFF_MAX_LOOPS],
        ideal_moves=words[OFF_IDEAL_MOVES],
        header_flags=words[OFF_HEADER_FLAGS],
    )
