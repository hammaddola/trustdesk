import { createContext } from "react";

/** Light-DOM elements owned by the widget host (for third-party iframes that cannot live in a shadow root). */
export interface LightDom {
  captchaSlot: HTMLElement;
}

export const LightDomContext = createContext<LightDom | null>(null);
