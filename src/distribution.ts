export function supportsPrivateTools(version: string): boolean {
  const match = /^(?:v)?(\d+)\.(\d+)\.(\d+)-(?:lab|test)\.\d+$/.exec(version);
  if (!match) return false;
  const [major, minor] = match.slice(1, 3).map(Number);
  return major < 1 || (major === 1 && minor < 5);
}
