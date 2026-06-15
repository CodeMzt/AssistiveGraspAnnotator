import { describe, expect, it } from "vitest";
import { axisAngle, hitTest } from "./geometry";
import type { Annotation } from "./types";

function annotation(): Annotation {
  return {
    image_id: "camera_1/image.png",
    image_path: "images/camera_1/image.png",
    width: 640,
    height: 480,
    camera: "camera_1",
    source: "manual",
    split: "train",
    objects: [
      {
        instance_id: 1,
        class_id: 0,
        class_name: "phial",
        bbox_xyxy: [100, 100, 300, 260],
        graspable: true,
        template_id: "phial",
        yaw_label_status: "valid",
        occlusion_level: 0,
        difficulty: "easy",
        main_axis_points: [[140, 160], [220, 160]],
        notes: "",
      }
    ]
  };
}

describe("hitTest", () => {
  it("hits bbox handles before bbox body", () => {
    expect(hitTest(annotation(), [100, 100], 12)).toEqual({
      objectId: 1,
      handle: "nw"
    });
  });

  it("hits bbox body and empty space", () => {
    expect(hitTest(annotation(), [280, 240], 12)).toEqual({
      objectId: 1,
      handle: "body"
    });
    expect(hitTest(annotation(), [20, 20], 12)).toEqual({
      objectId: null,
      handle: null
    });
  });

  it("hits axis handles", () => {
    expect(hitTest(annotation(), [140, 160], 12)).toEqual({
      objectId: 1,
      handle: "axis0"
    });
    expect(hitTest(annotation(), [220, 160], 12)).toEqual({
      objectId: 1,
      handle: "axis1"
    });
  });
});

describe("axisAngle", () => {
  it("computes angle from 2-point axis", () => {
    // Horizontal axis pointing right
    expect(axisAngle([[0, 0], [100, 0]])).toBeCloseTo(0, 5);
    // Vertical axis pointing down
    expect(axisAngle([[0, 0], [0, 100]])).toBeCloseTo(Math.PI / 2, 5);
    // 45-degree axis
    expect(axisAngle([[0, 0], [100, 100]])).toBeCloseTo(Math.PI / 4, 5);
  });
});
