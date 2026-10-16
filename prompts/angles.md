# Design angles

Generic angles that work for most features. Put the ones you want into `[variants].angles`
(in order: variant a gets the first, b the second, ...). Feature-specific angles work better;
write them like these: a short name, a colon, the decision it forces.

- minimal: the smallest correct implementation; no options, no cleverness
- robust: edge cases and hostile input first; defensive, explicit errors
- user-facing: optimise for what a human reads or sees; readability over fidelity
- standards-literal: follow the relevant spec/RFC/convention to the letter, cite it in notes
- performance: optimise speed and memory; measure it in notes
- extensible: configurable/pluggable, designed for the next three requirements
- locale-aware: language, region and script specifics are first-class
- unconventional: solve it in a way most developers would not try first
- functional: pure functions, data in, data out, no hidden state
- compatibility: mirror a popular existing library's behaviour (name it), drop-in replacement
