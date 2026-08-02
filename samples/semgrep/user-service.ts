/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for mutation-requires-authz-ts, which only applies to files matching
 * *service.ts / *handler.ts — hence the filename.
 */

interface Authz {
  require(permission: string): Promise<void>;
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

  // NOT flagged: a read, not a mutation.
  async readUser(id: string): Promise<string> {
    return this.repo.read(id);
  }
}
