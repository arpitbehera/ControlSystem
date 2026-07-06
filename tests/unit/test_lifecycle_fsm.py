import pytest

from device_servers._base.fsm import DeviceState, LifecycleFsm, Verb


def test_happy_path() -> None:
    fsm = LifecycleFsm()
    assert fsm.state is DeviceState.UNINIT
    for verb, expected in [
        (Verb.CONFIGURE, DeviceState.CONFIGURED),
        (Verb.ARM, DeviceState.ARMED),
        (Verb.START, DeviceState.RUNNING),
        (Verb.STOP, DeviceState.STOPPED),
        (Verb.DISARM, DeviceState.UNINIT),
    ]:
        result = fsm.apply(verb)
        assert result.ok and not result.noop
        assert fsm.state is expected


def test_same_verb_same_state_is_noop_success() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    result = fsm.apply(Verb.CONFIGURE)
    assert result.ok and result.noop
    assert fsm.state is DeviceState.CONFIGURED


def test_invalid_transition_rejected_without_state_change() -> None:
    fsm = LifecycleFsm()
    result = fsm.apply(Verb.START)
    assert not result.ok and result.error is not None
    assert fsm.state is DeviceState.UNINIT


def test_disarm_forces_reconfigure_before_next_arm() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.DISARM)
    assert fsm.state is DeviceState.UNINIT
    assert not fsm.apply(Verb.ARM).ok


def test_direct_disarm_from_running_is_emergency_teardown() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.START)
    result = fsm.apply(Verb.DISARM)
    assert result.ok
    assert fsm.state is DeviceState.UNINIT
    assert not fsm.apply(Verb.ARM).ok


def test_fault_then_disarm_recovers_to_uninit() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.START)
    fsm.fault("driver exploded")
    assert fsm.state is DeviceState.FAULT
    assert not fsm.apply(Verb.START).ok
    result = fsm.apply(Verb.DISARM)
    assert result.ok
    assert fsm.state is DeviceState.UNINIT


@pytest.mark.parametrize("verb", [Verb.CONFIGURE, Verb.ARM, Verb.START, Verb.STOP])
def test_only_disarm_leaves_fault(verb: Verb) -> None:
    fsm = LifecycleFsm()
    fsm.fault("x")
    assert not fsm.apply(verb).ok
