import { translate } from "./i18n";
import { performanceWarningParagraphs, PERFORMANCE_WARNING_TITLE } from "./faceplate_performance_warning";

// Explicit RGB values remain legible against the native dark Steam dialog.
export const PERFORMANCE_WARNING_YELLOW = "#ffd166";
export const PERFORMANCE_WARNING_RED = "#ff9090";

export function performanceWarningTitle() {
  return <span style={{ color: PERFORMANCE_WARNING_YELLOW, fontWeight: 700 }}>
    {translate(PERFORMANCE_WARNING_TITLE)}
  </span>;
}

export function performanceWarningContent(seconds = 5) {
  const paragraphs = performanceWarningParagraphs(seconds);
  return <div style={{ fontSize: 14, lineHeight: 1.45, whiteSpace: "normal" }}>
    {paragraphs.map((text, index) => <p key={index} style={{ margin: "0 0 12px",
      ...(index === paragraphs.length - 1 ? { color: PERFORMANCE_WARNING_RED, fontWeight: 600 } : {}) }}>
      {text}
    </p>)}
  </div>;
}
