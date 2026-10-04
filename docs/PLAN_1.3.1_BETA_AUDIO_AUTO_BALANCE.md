# GabeCubeAura v1.3.1-beta.1 plan

## Goal

Add an optional Audio Sync Auto Balance engine that keeps the Steam Machine
light bar expressive across quiet, normally mastered and heavily compressed
games without requiring a separate sensitivity calibration for every title.

The existing 1.3.0 renderers remain available. Auto Balance changes the signal
conditioning that feeds them, not LED ownership, provider priority or the
meaning of each pattern.

## User-facing result

- Auto Balance is enabled by default for Audio Sync.
- Manual keeps the current sensitivity behavior as a fallback.
- Character offers Natural, Balanced and Expressive. It controls attack,
  release and transient emphasis, not raw gain.
- Colour offers Natural and Vivid for the three-colour screen palette.
- Brightness remains the final hardware ceiling.
- Sensitivity is disabled in Auto mode and becomes available in Manual mode.
- The Audio Sync page reports Learning, Balanced or Limited so adaptation is
  visible without exposing internal DSP values in the normal interface.

No per-game calibration is required. A future per-AppID override can select
Auto or Manual, but v1.3.1-beta.1 should not persist learned loudness profiles.

## Signal path

1. Capture the active PipeWire sink monitor as stereo S16LE at 48 kHz.
2. Keep the current 2048-sample FFT and 60 ms renderer cadence.
3. Convert spectral decibels back to linear amplitude before averaging bass,
   middle and high-frequency energy. Do not average normalized byte bins because
   that raises the noise bed and can flatten every band near its ceiling.
4. Feed each band into a rolling robust normalizer.
5. Derive bass, middle and high spectral flux from positive FFT-bin changes,
   then normalize each flux against its own recent median and 94th percentile.
6. Derive stereo position from the normalized left/right energy ratio.
7. Feed normalized values into the selected existing 17-pixel renderer.
8. Apply fixed Steam Machine gamma, brightness ceiling and diffuser
   compensation only after content adaptation.

The automatic stage must remain deterministic, local and dependency-free.

## Rolling normalization

Create an `AudioAutoBalance` component owned by `AudioSyncProcessor`.

For bass, middle, high and shared stereo energy:

- Keep a bounded 10-second ring buffer.
- Estimate the noise floor with the 15th percentile.
- Estimate useful headroom with the 92nd percentile.
- Require a minimum dynamic span so silence cannot be amplified into noise.
- Smooth the estimated floor and headroom independently.
- Use a soft-knee compressor above useful headroom instead of hard clipping.
- Reserve true black for measured silence. A valid low-level signal keeps a
  gentle 12 to 20 percent visual bed so the pulse remains readable.
- Map the estimated floor above that visual bed instead of subtracting it to
  zero. Percentiles describe the useful range, not an audio noise gate.
- Reset on capture restart, PipeWire session replacement and explicit preview
  restart.

The first second uses conservative seeded ranges. From one to four seconds the
engine reports Learning. After enough samples it reports Balanced. If several
bands remain above the safe ceiling, it reports Limited while keeping colour
and motion rather than flattening the complete bar.

The normalizer must not chase a single explosion, menu click or quiet pause.
Percentiles update every 400 to 500 ms while the signal itself still renders at
the normal frame cadence.

The objective is a pleasant visual pulse, not reference loudness metering. A
steady musical passage must keep visible colour and small motion after the full
10-second window is populated. Only actual silence may converge to black.

## Transients and stereo

Transient detection uses spectral flux, not only the increase of an averaged
bass band. Keep only positive bin changes, compare them with an adaptive recent
threshold and add a short refractory period so one impact does not create
several pulses. This preserves a drum attack even when the surrounding passage
is already loud.

Keep separate time scales instead of one smoothing value:

- fast peak envelopes expose bass impact, middle attack and high texture;
- a slow musical bed preserves colour between attacks;
- peak holds and releases are time-based so their motion does not change with
  renderer frame rate;
- silence detection remains independent from the visual bed.

The global audio pulse uses two envelopes after normalization:

- a fast envelope follows attacks and short falls;
- a slow envelope tracks the average musical bed;
- their positive difference adds crest motion to a restrained base brightness;
- the public pulse remains between 16 and 82 percent while audio is present;
- measured silence still fades to black.

Do not build the pulse by summing two normalized stereo channels and a band
maximum. That formula reaches 100 percent for most mastered material and makes
the complete strip visually static.

Stereo field uses one shared loudness range for both channels. Normalizing the
channels independently would erase the original balance. Apply bounded width
expansion only after computing the left/right ratio:

- minimum width factor: 0.92;
- normal maximum: 1.28;
- return smoothly toward the centre when the signal becomes mono or quiet.

This preserves direction without making small encoding differences pin the
light to one edge.

## Screen-colour palette

For Screen colours + audio pulse and Screen colours + stereo field:

- derive candidates from the raw 34 by 18 Gamescope capture before reducing it
  to 17 display zones;
- cluster in OKLab;
- keep exactly three roles: ambience, shoulder and centre;
- reject near-black pixels and low-information highlights;
- keep the previous role assignment when colours remain perceptually close;
- require three consecutive samples before accepting a scene replacement;
- crossfade accepted palettes over 350 to 650 ms;
- let Natural preserve source chroma and let Vivid add bounded chroma only.

Audio energy controls brightness and motion. It must not continuously rotate or
reorder the three palette roles.

## Hi-Fi Crest pattern

Make Hi-Fi Crest the primary new renderer candidate. It is designed around the
information enthusiasts repeatedly ask visualizers to preserve: visible peaks,
peak versus average level, stereo direction, log-frequency separation and a
display that moves with musical attacks rather than only getting brighter.

Map the analysis to broad optical zones that survive the Steam Machine
diffuser:

- bass impact occupies the centre;
- middle attack occupies two mirrored shoulders;
- high-frequency texture occupies both edges;
- stereo balance weights the two sides without changing the colour roles;
- a strong bass onset launches one restrained centre-out crest;
- the three screen-derived colours remain stable and form gradients between
  the zones.

The renderer must never turn the full strip into a single uniformly scaled
colour. Narrow one-LED details, random rainbow rotation and persistent white
cores are rejected because the physical diffuser either erases them or makes
them look clipped.

The design basis is consistent with EBU-style separate momentary and short-term
time scales, Web Audio float decibel data, spectral-flux onset detection and
the peak hold, peak/RMS, stereo and perceptual frequency options common in
enthusiast analyzers. These are implementation references, not a claim that the
light bar is a calibrated measurement instrument.

Reference basis:

- EBU Tech 3341 for distinct 0.4-second momentary and 3-second short-term
  observation windows: <https://tech.ebu.ch/docs/tech/tech3341.pdf>
- W3C Web Audio for FFT data expressed as float decibels before conversion to
  linear amplitude: <https://www.w3.org/TR/webaudio-1.0/>
- foobar2000 Spectrum Analyzer for peak hold, peak/RMS, smoothing, perceptual
  frequency scales and artwork-derived colours in an enthusiast-oriented
  visualizer: <https://www.foobar2000.org/components/view/foo_vis_spectrum_analyzer>
- Roon community requests for synchronized peak hold, VU, true peak, stereo
  and correlation displays: <https://community.roonlabs.com/t/spectrum-analyser-graphic/3189>
- Music-to-colour research indicating that colour associations are strongly
  mediated by perceived emotion: <https://pmc.ncbi.nlm.nih.gov/articles/PMC4671663/>

## Renderer behavior

Auto Balance first targets these existing modes:

- Bass pulse;
- Screen colours + audio pulse;
- Stereo field;
- Screen colours + stereo field.

The 17-band Spectrum keeps one frequency bucket per LED. It can reuse the
per-band floor and headroom estimator, but it must not collapse to only three
bands.

Hi-Fi Crest remains experimental in v1.3.1-beta.1. The mockup presents the old
global pulse as a comparison so the loss of spatial information is visible. It
does not silently replace any public mode before physical validation.

## Ownership and lifecycle safeguards

The priority order must remain unchanged:

1. Steam hard system activity and native thermal warnings.
2. Critical playtime countdowns.
3. Short Light Events and controller alerts.
4. Game launch animations and regular countdowns.
5. The selected permanent display, including Audio Sync.

Auto Balance never writes directly to the hardware and never bypasses the
arbiter or renderer.

When the Steam screensaver takes Screen Sync ownership:

- stop Audio Sync capture before switching providers;
- keep the read-only Gamescope capture only when its session is still valid;
- close stale Gamescope and PipeWire processes when the session disappears;
- wait for the desktop or Gamescope session to settle;
- create a fresh audio normalizer when Audio Sync resumes.

The same reset applies when Steam changes from Gamescope to desktop mode. No
old node identifier, percentile history or analyser block may cross that
boundary.

## Planned code changes

- `py_modules/signalbar/providers/audio_sync.py`
  - add `AudioAutoBalance` and bounded percentile helpers;
  - expose raw band and channel energy before renderer gain;
  - add relative onset and bounded stereo widening;
  - add palette hysteresis and crossfade state;
  - keep Manual as the current processing path.
- `py_modules/signalbar/providers/screen_sync.py`
  - expose the raw 34 by 18 sample to Audio Sync without adding another capture
    process;
  - preserve the existing 17-zone Screen Sync output.
- `py_modules/signalbar/backend/engine.py`
  - reset Auto Balance on provider activation, session replacement and
    screensaver handoff;
  - preserve the current ownership and priority gates.
- `py_modules/signalbar/settings/store.py`, `src/types.ts`, `src/api.ts`
  - add validated Auto or Manual mode, Character and Colour settings.
- Audio Sync frontend page
  - show the new controls and compact state;
  - grey out Sensitivity in Auto mode;
  - keep the real 15-second preview path.
- `docs/AUDIO_SYNC.md`, README and changelog
  - explain adaptation, privacy, fallback and physical validation limits.

## Automated validation

Add tests for:

- the same signal at 0.25x, 1x and 2x gain converging to comparable output;
- quiet content remaining above the useful floor without amplifying silence;
- a steady local video remaining visibly animated after the 10-second window
  is full;
- loud compressed content retaining motion instead of staying saturated;
- independent bass, middle and high normalization;
- an isolated transient not redefining the rolling ceiling;
- relative bass onset at several source gains;
- spectral-flux onset alignment on bass, middle and high attacks;
- adaptive flux thresholds remaining responsive in both quiet and compressed
  passages;
- peak hold and release timing remaining stable across renderer frame rates;
- the global pulse retaining a useful percentile spread and frame-to-frame
  motion on `Karmelita Prime.mp4` instead of saturating;
- shared stereo normalization preserving left/right direction;
- stereo widening staying within bounds;
- raw 34 by 18 palette extraction retaining a small salient colour;
- three-frame palette hysteresis and bounded crossfade;
- exact 17-pixel, 0 to 255 output for every public style;
- stale capture rejection and reset after a PipeWire session change;
- screensaver handoff and return;
- Steam, thermal, countdown, Light Event, controller and launch priorities;
- Manual mode matching the 1.3.0 renderer output for the same input.

Add a diffuser-aware visual assertion that the centre, shoulders and edges each
remain broad enough to be distinguishable after optical blur. This is a useful
software guard, but it does not replace observation on the physical machine.

## Visual and physical validation

Use `Karmelita Prime.mp4` and `20260930_190029.mp4` as two deliberately different
sources. For each source, compare 0.5x, 1x and 1.7x input gain and record:

- time to leave Learning;
- average and peak brightness;
- percentage of frames limited;
- palette replacement count;
- left/right direction changes;
- capture and render latency.

Then validate on the physical Steam Machine with the diffuser in place:

- quiet ambience remains visible but does not glow constantly;
- combat impacts remain clear without turning the full strip white;
- colour roles remain readable through diffusion;
- changing games does not carry the previous title's calibration;
- Steam downloads and thermal warnings visibly take priority;
- screensaver entry and return do not crash Decky or the game;
- Gamescope to desktop and desktop to Gamescope transitions reconnect cleanly.

Software tests can validate the engine and ownership decisions. They cannot
confirm physical diffuser appearance or final reaction latency.

## Beta rollout

1. Implement behind `audio_sync_auto_balance`, default off in development.
2. Run the complete backend and frontend regression suite.
3. Package a local `v1.3.1-beta.1` build without publishing it.
4. Validate the two supplied videos off-device.
5. Enable Auto Balance on the target Steam Machine and complete the physical
   matrix.
6. Make Auto Balance the beta default only after the priority and session tests
   pass physically.
7. Keep Manual as an immediate fallback throughout the beta.

Release blocking failures are any ownership regression, session-transition
crash, stuck full-bright frame, persistent silence glow, reversed stereo field
or loss of the selected route after the screensaver.

## Out of scope for v1.3.1-beta.1

- machine learning, cloud analysis or network calls;
- persistent per-game loudness fingerprints;
- automatic system volume changes;
- changes to Valve, thermal or temporary-event priority;
- a new public Cinematic Field renderer;
- publishing to GitHub.
