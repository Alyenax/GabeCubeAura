export function supportsPrivateTools(version: string): boolean {
  return /^(?:v)?\d+\.\d+\.\d+-(?:lab|test)\.\d+$/.test(version);
}
