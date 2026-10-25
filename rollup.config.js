import deckyPlugin from "@decky/rollup";

const config = deckyPlugin({});
// No orphan source-map link in the installed runtime.
for (const current of Array.isArray(config) ? config : [config]) {
  for (const output of Array.isArray(current.output) ? current.output : [current.output]) {
    if (output) output.sourcemap = false;
  }
}
export default config;

