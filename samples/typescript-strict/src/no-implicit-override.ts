// PROVES: "noImplicitOverride": true.
//
// The failure this catches is a rename in the base class silently turning an
// override into a new, never-called method.
//
// MUST PRODUCE: TS4114 — samples/expected/tsc.json holds the line.
class Base {
  describe(): string {
    return 'base';
  }
}

export class Derived extends Base {
  describe(): string {
    return 'derived';
  }
}
