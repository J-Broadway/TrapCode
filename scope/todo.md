- [ ] Consolodate ts.exports.update() into ts.update() to reduce boilerplate
- [ ] Allow add `bpm` to `ts.MIDI` where sepcifying `bpm` will use an internal function to appropriately convert to `cycle`.
`bpm` and `cycle` cannot be defined together it has to be one or the other
midi = ts.MIDI(incomingVoice, bpm=ts.Context.bpm) # we still need to implement ts.Context
midi = ts.MIDI(incomingVoice, bpm=ts.Context.bpm, cycle=1) # cannot use both 
- [ ] Explroe bypass kwarg for PatternChain where events with bypass=True will be skipped over (regardless of playign or not playing). It is fundamentally different than 'mute' where 'mute' effectively creates a *ghost pattern* who's events are running in the background but not audible where 'bypass' is effectively a pass over. 