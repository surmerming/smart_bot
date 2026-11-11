/// <reference types="vite/client" />

import type { HTMLAttributes } from "react";

declare global {
  namespace JSX {
    interface IntrinsicElements {
      "xd-chat-widget": HTMLAttributes<HTMLElement> & {
        mode?: "inline" | "floating";
        "api-base"?: string;
        brand?: string;
      };
    }
  }
}
