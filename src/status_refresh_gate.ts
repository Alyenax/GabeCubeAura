/** A read started before/during a user write cannot replace its result. */
export function statusRefreshGate() {
  let revision = 0, writes = 0;
  return {
    ticket: () => revision,
    accepts: (ticket: number) => writes === 0 && ticket === revision,
    invalidate: () => { revision++; },
    writing: (active: boolean) => {
      revision++;
      writes = active ? writes + 1 : Math.max(0, writes - 1);
    },
  };
}
