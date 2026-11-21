"""Browser-side input scripts (upstream common/input-scripts.ts).

Keep these as source text: Playwright executes them in a browser realm where
Python-side bindings do not exist.
"""

FOCUSED_INPUT_FRAME_SCRIPT = """(() => {
  let element = document.activeElement;
  while (element?.shadowRoot?.activeElement) {
    element = element.shadowRoot.activeElement;
  }
  return element instanceof HTMLIFrameElement || element instanceof HTMLFrameElement
    ? element
    : null;
})()"""

SELECT_ALL_INPUT_SCRIPT = """(() => {
  let activeElement = document.activeElement;
  while (activeElement?.shadowRoot?.activeElement) {
    activeElement = activeElement.shadowRoot.activeElement;
  }

  if (
    activeElement instanceof HTMLInputElement ||
    activeElement instanceof HTMLTextAreaElement
  ) {
    try {
      activeElement.select();
      return true;
    } catch {
      return false;
    }
  }

  if (activeElement instanceof HTMLElement && activeElement.isContentEditable) {
    const selection = window.getSelection();
    if (!selection) return false;
    const range = document.createRange();
    range.selectNodeContents(activeElement);
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  }

  return false;
})()"""

__all__ = ["FOCUSED_INPUT_FRAME_SCRIPT", "SELECT_ALL_INPUT_SCRIPT"]
