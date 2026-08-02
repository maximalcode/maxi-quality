/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for mutation-requires-authz-ts, which only applies to files matching
 * *service.ts / *handler.ts — hence the filename.
 */

interface Authz {
  require(permission: string): Promise<void>;
  authorize(permission: string): Promise<void>;
}

interface Repo {
  delete(id: string): Promise<void>;
  update(id: string, name: string): Promise<void>;
  read(id: string): Promise<string>;
}

export class UserService {
  constructor(
    private readonly authz: Authz,
    private readonly repo: Repo,
  ) {}

  // FLAGGED: mutation with no authz gate.
  async deleteUser(id: string): Promise<void> {
    await this.repo.delete(id);
  }

  // FLAGGED: same — "the caller already checked" is not a check.
  async updateUser(id: string, name: string): Promise<void> {
    await this.repo.update(id, name);
  }

  // NOT flagged: gated correctly. Proves the rule is not just matching on name.
  async createUser(name: string): Promise<void> {
    await this.authz.require('user.create');
    await this.repo.update('new', name);
  }

  // The other two exemptions. The rule offers three escape hatches and only the
  // awaited `require` had a fixture. These are NEGATIVE controls: both method
  // names match the mutation regex, so a broken exemption shows up as an
  // UNEXPECTED finding in the manifest rather than as nothing at all.
  //
  // NOT flagged: the un-awaited form. A gate you forget to await is its own bug,
  // but it is not this rule's, and the rule says so by listing it.
  async setDisplayName(id: string, name: string): Promise<void> {
    this.authz.require('user.update');
    await this.repo.update(id, name);
  }

  // NOT flagged: the authorize spelling.
  async removeUser(id: string): Promise<void> {
    await this.authz.authorize('user.delete');
    await this.repo.delete(id);
  }

  // NOT flagged: a read, not a mutation.
  async readUser(id: string): Promise<string> {
    return this.repo.read(id);
  }
}
