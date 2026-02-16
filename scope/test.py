import flvfx as vfx
import trapscript as ts

ts.debug(True, level=1)

# Minimal smoke tests for current architecture:
# 1) MIDI.n auto-trigger
# 2) ts.comp manual trigger
# 3) ts.comp(parent=...) cleanup on parent release
ACTIVE_TEST = 2

_comp_chain = None


def createDialog():
    return ts.UI().form


def onTriggerVoice(incomingVoice):
    global _comp_chain

    if ACTIVE_TEST == 1:
        # MIDI context should auto-trigger on creation.
        ts.MIDI(incomingVoice, scale="c:major").n("0 2 4", cycle=2)
        print("[test1] MIDI auto-trigger active")

    elif ACTIVE_TEST == 2:
        # Comp context should be manual: explicit .trigger() call.
        if incomingVoice.note == 62:
          print('hello world')
          _comp_chain.stop()
        else:
            _comp_chain = ts.comp(scale="a:minor").n("0 2 4", cycle=2).trigger()

    elif ACTIVE_TEST == 3:
        # Manual trigger + voice-bound cleanup via parent=
        _comp_chain = ts.comp(scale="c5:major", parent=incomingVoice).n("0 2 4", cycle=2).trigger()
        print("[test3] Comp(parent=...) manual trigger active")


def onReleaseVoice(incomingVoice):
    ts.stop_patterns_for_voice(incomingVoice)
    for v in vfx.context.voices:
        if ts.get_parent(v) == incomingVoice:
            v.release()


def onTick():
    ts.update()
