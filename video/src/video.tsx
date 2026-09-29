import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { Audio, Video } from "@remotion/media";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";

const C = {
  ink: "#172840",
  blue: "#315eb6",
  blueDark: "#244c99",
  muted: "#5d708e",
  pale: "#f2f5fa",
  white: "#ffffff",
  amber: "#aa6c21",
  line: "#d3deed",
  teal: "#347d83",
};
const MONO = "IBM Plex Mono, monospace";
const SANS = "DM Sans, Arial, sans-serif";
const SCENES = [225, 250, 235, 270, 235, 260, 250, 225];
const OVERLAP = 15;
const STARTS = SCENES.map(
  (_, i) => SCENES.slice(0, i).reduce((a, b) => a + b, 0) - i * OVERLAP,
);
export const DURATION =
  SCENES.reduce((a, b) => a + b, 0) - (SCENES.length - 1) * OVERLAP;
const ease = (f: number, a: number, b: number) =>
  interpolate(f, [a, b], [0, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
const slow = (f: number, a: number, b: number) =>
  interpolate(f, [a, b], [0, 1], {
    easing: Easing.bezier(0.45, 0, 0.55, 1),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

const Cube: React.FC<{ size?: number; color?: string }> = ({
  size = 42,
  color = C.blue,
}) => (
  <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden>
    <path
      d="M8 13.5 20 7l12 6.5v13L20 33 8 26.5v-13Z"
      stroke={color}
      strokeWidth="2"
      strokeLinejoin="round"
    />
    <path
      d="m8.5 13.5 11.5 6 11.5-6M20 19.5V33"
      stroke={color}
      strokeWidth="2"
      strokeLinejoin="round"
    />
  </svg>
);

const FilmFrame: React.FC<{
  index: number;
  label: string;
  children: React.ReactNode;
  dark?: boolean;
}> = ({ index, label, children, dark = false }) => (
  <AbsoluteFill
    style={{
      background: dark ? "#15243b" : C.pale,
      color: dark ? C.white : C.ink,
      fontFamily: SANS,
      overflow: "hidden",
    }}
  >
    <AbsoluteFill
      style={{
        opacity: dark ? 0.11 : 0.28,
        backgroundImage: `linear-gradient(${dark ? "#8aa4ce" : C.line} 1px,transparent 1px),linear-gradient(90deg,${dark ? "#8aa4ce" : C.line} 1px,transparent 1px)`,
        backgroundSize: "72px 72px",
        maskImage: "linear-gradient(90deg,transparent 4%,black 48%,black 96%)",
      }}
    />
    <div
      style={{
        position: "absolute",
        left: 104,
        right: 104,
        top: 57,
        height: 52,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        zIndex: 5,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 13,
          fontSize: 30,
          fontWeight: 800,
          letterSpacing: -1.2,
        }}
      >
        <Cube size={38} color={dark ? "#8bb1ff" : C.blue} />
        <span>
          Pack<span style={{ color: dark ? "#8bb1ff" : C.blue }}>Sense</span>
        </span>
      </div>
      <div
        style={{
          fontFamily: MONO,
          fontSize: 14,
          letterSpacing: 2,
          color: dark ? "#a9bfdf" : C.muted,
        }}
      >
        {label}{" "}
        <span style={{ marginLeft: 20, opacity: 0.55 }}>
          {String(index + 1).padStart(2, "0")} / 08
        </span>
      </div>
    </div>
    {children}
    <div
      style={{
        position: "absolute",
        left: 104,
        right: 104,
        bottom: 50,
        zIndex: 8,
      }}
    >
      <div
        style={{
          height: 1,
          background: dark ? "#426082" : C.line,
          marginBottom: 19,
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontFamily: MONO,
          fontSize: 12,
          letterSpacing: 1.3,
          color: dark ? "#a9bfdf" : C.muted,
        }}
      >
        <span>FOOD → NEED → STRUCTURE → EVIDENCE</span>
        <span>PACKSENSE / PRODUCT DEMO</span>
      </div>
      <div style={{ display: "flex", gap: 5, marginTop: 15 }}>
        {SCENES.map((_, i) => (
          <div
            key={i}
            style={{
              height: 3,
              flex: 1,
              background:
                i <= index
                  ? dark
                    ? "#8bb1ff"
                    : C.blue
                  : dark
                    ? "#3a526e"
                    : "#d4deec",
            }}
          />
        ))}
      </div>
    </div>
  </AbsoluteFill>
);

const Eyebrow: React.FC<{ children: React.ReactNode; light?: boolean }> = ({
  children,
  light,
}) => (
  <div
    style={{
      fontFamily: MONO,
      fontSize: 16,
      fontWeight: 600,
      letterSpacing: 2.4,
      color: light ? "#92b7ff" : C.blue,
      marginBottom: 23,
    }}
  >
    {children}
  </div>
);
const Lead: React.FC<{
  children: React.ReactNode;
  small?: boolean;
  light?: boolean;
}> = ({ children, small = false, light = false }) => (
  <div
    style={{
      fontSize: small ? 64 : 76,
      lineHeight: 1.05,
      fontWeight: 700,
      letterSpacing: -3.8,
      color: light ? C.white : C.ink,
      maxWidth: 610,
    }}
  >
    {children}
  </div>
);
const Body: React.FC<{ children: React.ReactNode; light?: boolean }> = ({
  children,
  light,
}) => (
  <p
    style={{
      fontSize: 25,
      lineHeight: 1.42,
      color: light ? "#c8d9ee" : C.muted,
      maxWidth: 545,
      marginTop: 28,
    }}
  >
    {children}
  </p>
);

const BrowserCard: React.FC<{
  shot: string;
  clip?: string;
  trimBefore?: number;
  width?: number;
  x?: number;
  y?: number;
  zoom?: number;
  topLabel?: string;
}> = ({
  shot,
  clip,
  trimBefore = 0,
  width = 1130,
  x = 690,
  y = 205,
  zoom = 1,
  topLabel = "packsense-web.vercel.app",
}) => {
  const f = useCurrentFrame();
  const show = ease(f, 7, 29);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        transform: `translateY(${(1 - show) * 42}px) scale(${(0.975 + 0.025 * slow(f, 0, 170)) * zoom})`,
        transformOrigin: "center",
        opacity: show,
        borderRadius: 19,
        background: "#fff",
        border: "1px solid #bdcde5",
        boxShadow: "0 34px 76px rgba(31,57,101,.19)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: 42,
          background: "#f7f9fd",
          display: "flex",
          alignItems: "center",
          gap: 9,
          padding: "0 18px",
          borderBottom: "1px solid #dbe4f0",
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 9,
            background: "#afc0d9",
          }}
        />
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 9,
            background: "#afc0d9",
          }}
        />
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 9,
            background: "#afc0d9",
          }}
        />
        <span
          style={{
            margin: "0 auto",
            fontFamily: MONO,
            fontSize: 12,
            color: "#7c8da4",
          }}
        >
          {topLabel}
        </span>
      </div>
      {clip ? (
        <Video
          src={staticFile(`clips/${clip}`)}
          trimBefore={trimBefore}
          style={{ display: "block", width: "100%", aspectRatio: "16/9" }}
        />
      ) : (
        <Img
          src={staticFile(`screens/${shot}`)}
          style={{ display: "block", width: "100%", height: "auto" }}
        />
      )}
    </div>
  );
};

const Callout: React.FC<{
  x: number;
  y: number;
  n: string;
  title: string;
  width?: number;
  delay?: number;
}> = ({ x, y, n, title, width = 300, delay = 40 }) => {
  const f = useCurrentFrame();
  const p = ease(f, delay, delay + 22);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        display: "flex",
        alignItems: "center",
        gap: 15,
        background: "rgba(255,255,255,.97)",
        border: "1px solid #cad8ec",
        borderRadius: 10,
        padding: "14px 19px",
        boxShadow: "0 18px 36px rgba(29,51,85,.13)",
        transform: `translateY(${(1 - p) * 20}px)`,
        opacity: p,
      }}
    >
      <span style={{ fontFamily: MONO, color: C.blue, fontSize: 15 }}>{n}</span>
      <span style={{ fontWeight: 700, fontSize: 17 }}>{title}</span>
    </div>
  );
};

const Hook = () => {
  const f = useCurrentFrame();
  const p = ease(f, 2, 35);
  return (
    <FilmFrame index={0} label="THE QUESTION" dark>
      <div
        style={{
          position: "absolute",
          left: 107,
          top: 247,
          width: 960,
          opacity: p,
          transform: `translateY(${(1 - p) * 45}px)`,
        }}
      >
        <Eyebrow light>FOOD PACKAGING / DECISION INTELLIGENCE</Eyebrow>
        <div
          style={{
            fontSize: 105,
            lineHeight: 1.02,
            letterSpacing: -6.5,
            fontWeight: 700,
          }}
        >
          Food first.
          <br />
          <span style={{ color: "#8bb1ff" }}>Evidence always.</span>
        </div>
        <Body light>
          From a real food scenario to a decision you can explain.
        </Body>
      </div>
      <svg
        style={{
          position: "absolute",
          right: 118,
          top: 195,
          width: 655,
          height: 590,
        }}
        viewBox="0 0 655 590"
        fill="none"
      >
        <circle
          cx="315"
          cy="286"
          r="202"
          stroke="#51709c"
          strokeWidth="1"
          strokeDasharray="4 10"
        />
        <circle
          cx="315"
          cy="286"
          r={112 * ease(f, 14, 54)}
          stroke="#7299d1"
          strokeWidth="1"
        />
        <path
          d="M20 286h130m338 0h150"
          stroke="#81a9e5"
          strokeWidth="2"
          strokeDasharray="150"
          strokeDashoffset={150 * (1 - ease(f, 15, 53))}
        />
        <path
          d="M210 238 317 189l109 49v104l-109 52-107-52V238Z M210 238l107 50 109-50M317 288v106"
          stroke="#91b8f5"
          strokeWidth="3"
          strokeLinejoin="round"
          strokeDasharray="750"
          strokeDashoffset={750 * (1 - ease(f, 28, 103))}
        />
        <circle
          cx="65"
          cy="286"
          r="55"
          stroke="#91b8f5"
          strokeWidth="2"
          opacity={ease(f, 18, 45)}
        />
        <path
          d="M42 300c2-26 17-40 44-39-2 26-19 41-44 39Zm4-2 40-37"
          stroke="#91b8f5"
          strokeWidth="2"
          opacity={ease(f, 18, 45)}
        />
        <circle
          cx="573"
          cy="286"
          r="55"
          stroke="#91b8f5"
          strokeWidth="2"
          opacity={ease(f, 80, 110)}
        />
        <circle
          cx="567"
          cy="280"
          r="17"
          stroke="#91b8f5"
          strokeWidth="2"
          opacity={ease(f, 80, 110)}
        />
        <path
          d="m581 294 18 18"
          stroke="#91b8f5"
          strokeWidth="2"
          opacity={ease(f, 80, 110)}
        />
        <text
          x="18"
          y="372"
          fill="#a9bfdf"
          fontFamily={MONO}
          fontSize="14"
          letterSpacing="2"
        >
          FOOD
        </text>
        <text
          x="246"
          y="466"
          fill="#a9bfdf"
          fontFamily={MONO}
          fontSize="14"
          letterSpacing="2"
        >
          PACKAGE
        </text>
        <text
          x="530"
          y="372"
          fill="#a9bfdf"
          fontFamily={MONO}
          fontSize="14"
          letterSpacing="2"
        >
          PROOF
        </text>
      </svg>
    </FilmFrame>
  );
};

const Food = () => (
  <FilmFrame index={1} label="01 / SELECT THE FOOD">
    <div style={{ position: "absolute", left: 105, top: 270 }}>
      <Eyebrow>A SOURCED STARTING POINT</Eyebrow>
      <Lead>
        Start with
        <br />
        the food.
      </Lead>
      <Body>
        Search a food reference with reported composition and a visible source
        basis.
      </Body>
      <div
        style={{ marginTop: 40, fontFamily: MONO, color: C.blue, fontSize: 17 }}
      >
        FND-2710823 / ASPARAGUS
      </div>
    </div>
    <BrowserCard
      shot="03-evaluate.jpg"
      clip="food-and-journey.mp4"
      x={690}
      y={204}
      width={1130}
    />
    <Callout
      x={1170}
      y={695}
      n="01"
      title="Source reference selected"
      width={430}
      delay={55}
    />
  </FilmFrame>
);

const Journey = () => (
  <FilmFrame index={2} label="02 / ADD THE CONDITIONS">
    <div style={{ position: "absolute", left: 105, top: 260 }}>
      <Eyebrow>FROM REFERENCE TO SCENARIO</Eyebrow>
      <Lead>
        Add the
        <br />
        real journey.
      </Lead>
      <Body>
        Set the life target, cold chain, transport exposure, handling, and pack
        quantity for this product.
      </Body>
      <div
        style={{
          marginTop: 40,
          padding: "17px 22px",
          borderLeft: `3px solid ${C.amber}`,
          background: "#fff9ed",
          maxWidth: 530,
          fontSize: 18,
          color: C.amber,
        }}
      >
        Targets and journey inputs are submitted conditions.
      </div>
    </div>
    <BrowserCard shot="03b-journey.jpg" x={690} y={205} width={1130} />
    <Callout
      x={1210}
      y={691}
      n="02"
      title="Storage + transport inputs"
      width={420}
      delay={60}
    />
  </FilmFrame>
);

const Needs = () => {
  const f = useCurrentFrame();
  const nodes = [
    { x: 130, y: 258, t: "FOOD", s: "identity · composition" },
    { x: 130, y: 503, t: "JOURNEY", s: "storage · transport" },
    { x: 785, y: 198, t: "OXYGEN", s: "ingress / gas balance" },
    { x: 785, y: 350, t: "MOISTURE", s: "gain / loss" },
    { x: 785, y: 502, t: "HANDLING", s: "mechanical integrity" },
    { x: 785, y: 654, t: "CONTACT", s: "food safety review" },
  ];
  return (
    <FilmFrame index={3} label="03 / DEFINE PROTECTION" dark>
      <div style={{ position: "absolute", left: 108, top: 150 }}>
        <Eyebrow light>THE DECISION ENGINE</Eyebrow>
        <div style={{ fontSize: 61, fontWeight: 700, letterSpacing: -2.5 }}>
          Translate conditions into protection needs.
        </div>
      </div>
      <svg
        style={{
          position: "absolute",
          left: 130,
          top: 290,
          width: 1640,
          height: 590,
        }}
        viewBox="0 0 1640 590"
        fill="none"
      >
        <path
          d="M390 75h160v315h102 M390 320h160"
          stroke="#5e86bd"
          strokeWidth="2"
          strokeDasharray="850"
          strokeDashoffset={850 * (1 - ease(f, 27, 84))}
        />
        <path
          d="M650 70v405"
          stroke="#5e86bd"
          strokeWidth="2"
          strokeDasharray="405"
          strokeDashoffset={405 * (1 - ease(f, 55, 96))}
        />
        {[60, 212, 364, 516].map((y, i) => (
          <path
            key={i}
            d={`M650 ${y}h52`}
            stroke="#8bb1ff"
            strokeWidth="2"
            opacity={ease(f, 65 + i * 12, 85 + i * 12)}
          />
        ))}
      </svg>
      {nodes.map((n, i) => {
        const p = ease(f, 15 + i * 15, 40 + i * 15);
        return (
          <div
            key={n.t}
            style={{
              position: "absolute",
              left: n.x + (i < 2 ? 95 : 0),
              top: n.y + (i < 2 ? 105 : 140),
              width: i < 2 ? 300 : 455,
              height: 102,
              background: i < 2 ? "#1e3553" : "#203955",
              border: "1px solid #668dbf",
              borderRadius: 10,
              padding: "22px 27px",
              opacity: p,
              transform: `translateY(${(1 - p) * 25}px)`,
            }}
          >
            <div
              style={{
                fontFamily: MONO,
                fontSize: 16,
                letterSpacing: 1.8,
                color: "#99bdff",
              }}
            >
              {n.t}
            </div>
            <div style={{ fontSize: 19, marginTop: 9, color: "#d2e1f6" }}>
              {n.s}
            </div>
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          right: 130,
          top: 450,
          width: 345,
          fontSize: 31,
          lineHeight: 1.2,
          fontWeight: 700,
          color: "#b6d0f7",
        }}
      >
        Every need becomes a visible check.
      </div>
    </FilmFrame>
  );
};

const Screen = () => {
  const f = useCurrentFrame();
  const p = ease(f, 45, 110);
  return (
    <FilmFrame index={4} label="04 / SCREEN THE STRUCTURE">
      <div style={{ position: "absolute", left: 105, top: 265 }}>
        <Eyebrow>COMPLETE PACKAGE / REAL EVIDENCE</Eyebrow>
        <Lead>
          Screen the
          <br />
          structure.
        </Lead>
        <Body>
          Supplier listings are useful leads. They still need package, transfer,
          contact, and service evidence.
        </Body>
      </div>
      <BrowserCard shot="05-pipeline.jpg" x={680} y={202} width={1150} />
      <svg
        style={{
          position: "absolute",
          left: 1200,
          top: 490,
          width: 510,
          height: 290,
          pointerEvents: "none",
        }}
        viewBox="0 0 510 290"
        fill="none"
      >
        <path
          d="m90 96 145-64 145 64-145 64L90 96Zm0 35 145 65 145-65M90 166l145 65 145-65"
          stroke="#315eb6"
          strokeWidth="3"
          strokeDasharray="1200"
          strokeDashoffset={1200 * (1 - p)}
        />
        <circle
          cx="235"
          cy="125"
          r="103"
          stroke="#315eb6"
          strokeWidth="1"
          strokeDasharray="4 7"
          opacity={p}
        />
      </svg>
    </FilmFrame>
  );
};

const Result = () => {
  const f = useCurrentFrame();
  const p = ease(f, 45, 76);
  return (
    <FilmFrame index={5} label="05 / READ THE DECISION">
      <div style={{ position: "absolute", left: 105, top: 250 }}>
        <Eyebrow>LIVE EVALUATION</Eyebrow>
        <Lead>
          Honest result.
          <br />
          <span style={{ color: C.amber }}>Needs evidence.</span>
        </Lead>
        <Body>
          In the submitted asparagus scenario, eight checks remain open. No
          package or shelf life is approved.
        </Body>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            marginTop: 42,
            opacity: p,
          }}
        >
          <strong style={{ fontSize: 90, color: C.amber, lineHeight: 1 }}>
            08
          </strong>
          <span
            style={{
              fontFamily: MONO,
              fontSize: 18,
              letterSpacing: 1,
              color: C.muted,
            }}
          >
            RECORDED
            <br />
            EVIDENCE GAPS
          </span>
        </div>
      </div>
      <BrowserCard
        shot="09-live-result.jpg"
        clip="fresh-result.mp4"
        x={680}
        y={200}
        width={1150}
      />
      <Callout
        x={1140}
        y={686}
        n="STATUS"
        title="Needs evidence · no approval"
        width={480}
        delay={55}
      />
    </FilmFrame>
  );
};

const Evidence = () => {
  const f = useCurrentFrame();
  return (
    <FilmFrame index={6} label="06 / FOLLOW THE TRACE">
      <div style={{ position: "absolute", left: 105, top: 257 }}>
        <Eyebrow>TRACEABILITY BUILT IN</Eyebrow>
        <Lead>
          Every result
          <br />
          has a trace.
        </Lead>
        <Body>
          Inspect the record, follow its citations, and see which batch inputs
          have fingerprints.
        </Body>
        <div style={{ display: "flex", gap: 8, marginTop: 38 }}>
          {["USDA FDC", "pH BASIS", "SUPPLIER USE"].map((x, i) => (
            <span
              key={x}
              style={{
                border: "1px solid #bfd0ea",
                borderRadius: 4,
                padding: "10px 13px",
                fontFamily: MONO,
                fontSize: 12,
                color: C.blue,
                opacity: ease(f, 45 + i * 10, 67 + i * 10),
              }}
            >
              {x}
            </span>
          ))}
        </div>
      </div>
      <BrowserCard
        shot="10-live-evidence.jpg"
        clip="fresh-evidence.mp4"
        x={680}
        y={200}
        width={1150}
      />
      <Callout
        x={1150}
        y={692}
        n="SHA-256"
        title="Input fingerprints retained"
        width={455}
        delay={63}
      />
    </FilmFrame>
  );
};

const Close = () => {
  const f = useCurrentFrame();
  const p = ease(f, 5, 40);
  return (
    <FilmFrame index={7} label="DECISIONS YOU CAN EXPLAIN" dark>
      <div
        style={{
          position: "absolute",
          left: 180,
          top: 265,
          opacity: p,
          transform: `translateY(${(1 - p) * 44}px)`,
        }}
      >
        <Eyebrow light>PACKSENSE / EVIDENCE-LED SCREENING</Eyebrow>
        <div
          style={{
            fontSize: 113,
            lineHeight: 1.03,
            fontWeight: 700,
            letterSpacing: -7,
          }}
        >
          Food first.
          <br />
          <span style={{ color: "#8bb1ff" }}>Evidence always.</span>
        </div>
        <div style={{ fontSize: 29, color: "#d2e1f6", marginTop: 40 }}>
          See the decision path for yourself.
        </div>
        <div
          style={{
            marginTop: 36,
            display: "inline-flex",
            alignItems: "center",
            gap: 20,
            background: "#8bb1ff",
            color: "#15243b",
            padding: "20px 30px",
            borderRadius: 7,
            fontSize: 23,
            fontWeight: 700,
          }}
        >
          packsense-web.vercel.app <span>↗</span>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          right: 150,
          top: 260,
          opacity: 0.23,
          transform: `scale(${0.9 + 0.1 * slow(f, 0, 180)})`,
        }}
      >
        <Cube size={500} color="#b9d2fb" />
      </div>
      <div
        style={{
          position: "absolute",
          left: 180,
          bottom: 165,
          color: "#a9bfdf",
          fontFamily: MONO,
          fontSize: 14,
          letterSpacing: 0.5,
        }}
      >
        SOURCE-BACKED DEMO · ILLUSTRATIVE CONDITIONS · NO DEPLOYED MATERIAL OR
        SHELF-LIFE PREDICTOR
      </div>
    </FilmFrame>
  );
};

const scenes = [Hook, Food, Journey, Needs, Screen, Result, Evidence, Close];
export const PackSenseFilm: React.FC = () => (
  <AbsoluteFill>
    <TransitionSeries>
      {scenes.map((Scene, i) => (
        <React.Fragment key={i}>
          <TransitionSeries.Sequence durationInFrames={SCENES[i]}>
            <Scene />
          </TransitionSeries.Sequence>
          {i < scenes.length - 1 ? (
            <TransitionSeries.Transition
              presentation={fade()}
              timing={linearTiming({ durationInFrames: OVERLAP })}
            />
          ) : null}
        </React.Fragment>
      ))}
    </TransitionSeries>
    <Audio src={staticFile("audio/score.mp3")} volume={0.35} />
    {STARTS.map((start, i) => (
      <Sequence key={i} from={start + 10} layout="none">
        <Audio
          src={staticFile(`audio/voice-${String(i + 1).padStart(2, "0")}.mp3`)}
          volume={1}
        />
      </Sequence>
    ))}
  </AbsoluteFill>
);
