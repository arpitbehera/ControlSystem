import pytest

from broker.rearrangement_batch import (
    BATCH_WORDS,
    HEADER_WORDS,
    MOVE_WORDS,
    N_MAX_MOVES,
    OFF_IDEAL_MOVES,
    OFF_N_MOVES,
    OFF_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    Move,
    decode_header,
    encode_batch,
)


def _moves(n: int) -> list[Move]:
    return [
        Move(src_x=i, src_y=0, tgt_x=i, tgt_y=1, group_id=0, t_ramp_ticks=100, flags=0)
        for i in range(n)
    ]


def test_batch_words_constant() -> None:
    assert HEADER_WORDS == 16 and MOVE_WORDS == 6
    assert BATCH_WORDS == HEADER_WORDS + N_MAX_MOVES * MOVE_WORDS == 6160


def test_encode_is_fixed_width_and_padded() -> None:
    words = encode_batch(
        sequence_no=1,
        deadline_ppu_ticks=10_000,
        snapshot_hash64=0xAABB,
        descriptor_hash64=0xCCDD,
        loop_index=0,
        max_loops=3,
        ideal_moves=3,
        moves=_moves(3),
    )
    assert len(words) == BATCH_WORDS
    assert words[OFF_PROTOCOL_VERSION] == PROTOCOL_VERSION
    assert words[OFF_N_MOVES] == 3
    assert words[HEADER_WORDS + 3 * MOVE_WORDS :] == [0] * (
        (N_MAX_MOVES - 3) * MOVE_WORDS
    )


def test_header_roundtrip_including_64bit_fields() -> None:
    deadline = (1 << 40) + 12345
    words = encode_batch(
        sequence_no=7,
        deadline_ppu_ticks=deadline,
        snapshot_hash64=(1 << 63) | 5,
        descriptor_hash64=42,
        loop_index=1,
        max_loops=3,
        ideal_moves=2,
        moves=_moves(2),
    )
    header = decode_header(words)
    assert header.sequence_no == 7
    assert header.deadline_ppu_ticks == deadline
    assert header.snapshot_hash64 == (1 << 63) | 5
    assert header.loop_index == 1 and header.max_loops == 3
    assert max(words[:HEADER_WORDS]) <= 0x7FFF_FFFF


def test_truncation_signal_ideal_gt_n_moves_allowed() -> None:
    words = encode_batch(
        sequence_no=1,
        deadline_ppu_ticks=1,
        snapshot_hash64=0,
        descriptor_hash64=0,
        loop_index=0,
        max_loops=3,
        ideal_moves=N_MAX_MOVES + 50,
        moves=_moves(2),
    )
    assert words[OFF_IDEAL_MOVES] == N_MAX_MOVES + 50
    assert words[OFF_N_MOVES] == 2


def test_too_many_moves_rejected() -> None:
    with pytest.raises(ValueError):
        encode_batch(
            sequence_no=1,
            deadline_ppu_ticks=1,
            snapshot_hash64=0,
            descriptor_hash64=0,
            loop_index=0,
            max_loops=3,
            ideal_moves=N_MAX_MOVES + 1,
            moves=_moves(N_MAX_MOVES + 1),
        )
