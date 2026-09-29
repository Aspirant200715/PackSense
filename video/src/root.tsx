import React from "react";
import { Composition } from "remotion";
import { PackSenseFilm, DURATION } from "./video";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="PackSenseProductDemo"
    component={PackSenseFilm}
    durationInFrames={DURATION}
    fps={30}
    width={1920}
    height={1080}
  />
);
