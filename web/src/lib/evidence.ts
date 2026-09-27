import type { CSSProperties } from "react";

import type { ApiSchema } from "./api/client";

export function bboxStyle(bbox: ApiSchema<"BoundingBox">): CSSProperties {
  return {
    left: `${bbox.x0 * 100}%`,
    top: `${bbox.y0 * 100}%`,
    width: `${(bbox.x1 - bbox.x0) * 100}%`,
    height: `${(bbox.y1 - bbox.y0) * 100}%`,
  };
}
