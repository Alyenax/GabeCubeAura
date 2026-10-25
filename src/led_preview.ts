import type {RGB} from './types';

export type LedPreviewChannel = 'output' | 'weather' | 'customization' | 'events' | 'controllers'
  | 'countdown' | 'screen_sync' | 'audio_sync' | 'launch_artwork' | 'performance' | 'artwork';
export type LedPreviewFrames = Partial<Record<LedPreviewChannel, RGB[]>>;
type Listener = (frame: RGB[] | undefined) => void;
type Timer = ReturnType<typeof setTimeout>;
export const LED_PREVIEW_INTERVAL_MS = 50;

const validFrame = (frame: unknown): frame is RGB[] => Array.isArray(frame) && frame.length === 17
  && frame.every(pixel => Array.isArray(pixel) && pixel.length === 3
    && pixel.every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 255));

/** One shared, non-overlapping colour read for the previews currently on screen. */
export class LedPreviewStream {
  private listeners = new Map<LedPreviewChannel, Set<Listener>>();
  private timer: Timer | undefined;
  private busy = false;
  private visible = true;
  private revision = 0;
  private failures = 0;
  constructor(private read: (channels: LedPreviewChannel[]) => Promise<LedPreviewFrames>,
    private schedule = (task: () => void, delay: number) => setTimeout(task, delay),
    private cancel = (timer: Timer) => clearTimeout(timer)) {}

  subscribe(channel: LedPreviewChannel, listener: Listener) {
    let subscribers = this.listeners.get(channel);
    if (!subscribers) this.listeners.set(channel, subscribers = new Set());
    subscribers.add(listener);
    this.revision++;
    this.start();
    return () => {
      subscribers.delete(listener);
      if (!subscribers.size) this.listeners.delete(channel);
      this.revision++;
      if (!this.listeners.size) this.stop();
    };
  }
  setVisible(visible: boolean) {
    if (visible === this.visible) return;
    this.visible = visible;
    this.revision++;
    if (visible) this.start();
    else { this.stop(); this.clear(); }
  }
  private clear() {
    for (const subscribers of this.listeners.values()) for (const listener of subscribers) listener(undefined);
  }
  private stop() {
    if (this.timer !== undefined) this.cancel(this.timer);
    this.timer = undefined;
  }
  private start(delay = 0) {
    if (!this.visible || !this.listeners.size || this.busy || this.timer !== undefined) return;
    this.timer = this.schedule(() => { this.timer = undefined; void this.poll(); }, delay);
  }
  private async poll() {
    if (!this.visible || !this.listeners.size || this.busy) return;
    this.busy = true;
    const revision = this.revision;
    try {
      const frames = await this.read([...this.listeners.keys()]);
      this.failures = 0;
      if (revision === this.revision && this.visible) {
        for (const [channel, subscribers] of this.listeners) {
          const frame = frames?.[channel];
          for (const listener of subscribers) listener(validFrame(frame) ? frame : undefined);
        }
      }
    } catch {
      this.failures++;
      if (revision === this.revision) this.clear();
    } finally {
      this.busy = false;
      this.start(Math.min(1000, LED_PREVIEW_INTERVAL_MS * 2 ** Math.min(this.failures, 5)));
    }
  }
}
