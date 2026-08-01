"use client";

/** Passed and failed per run, most recent last.
 *
 *  Form: runs are discrete events, not a continuous series, so bars rather than
 *  a line. Stacked absolute counts rather than a pass-rate percentage, because
 *  the percentage hides the thing you most want to notice — "9/10" and "90/100"
 *  are the same number and very different weeks.
 *
 *  Colour: green/red is the classic dichromatic trap. Measured, it is ΔE 6.8
 *  under protanopia — inside the band that is only legal with a second channel.
 *  So every bar carries its counts as text, the legend is labelled, and the
 *  tooltip states the status in words. Colour is never doing the work alone.
 */

import { useState } from "react";

export interface TrendPoint {
  id: number;
  label: string;
  passed: number;
  failed: number;
  href?: string;
}

const BAR_W = 26;
const GAP = 12;
const H = 132;
const RADIUS = 4;
/** A 2px gap of surface between the two segments, so a stack never reads as
 *  one solid bar with a colour change halfway up. */
const SEGMENT_GAP = 2;

export function RunTrend({ points }: { points: TrendPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0) {
    return (
      <p className="py-8 text-center text-[13px] text-muted-foreground">
        No runs yet — the trend appears once you have run a suite.
      </p>
    );
  }

  const max = Math.max(...points.map((p) => p.passed + p.failed), 1);
  const width = points.length * BAR_W + (points.length - 1) * GAP;
  const active = points.find((p) => p.id === hover);

  return (
    <figure className="m-0">
      <div className="relative">
        <svg
          viewBox={`0 0 ${Math.max(width, 1)} ${H}`}
          width="100%"
          height={H}
          preserveAspectRatio="xMinYMax meet"
          role="img"
          aria-label={`Passed and failed tests across the last ${points.length} runs`}
          className="overflow-visible"
        >
          {points.map((point, index) => {
            const total = point.passed + point.failed;
            const x = index * (BAR_W + GAP);
            const fullH = (total / max) * (H - 22);
            const failH = total ? (point.failed / total) * fullH : 0;
            const passH = Math.max(fullH - failH - (failH ? SEGMENT_GAP : 0), 0);
            const dim = hover !== null && hover !== point.id;

            return (
              <g
                key={point.id}
                opacity={dim ? 0.45 : 1}
                onMouseEnter={() => setHover(point.id)}
                onMouseLeave={() => setHover(null)}
                style={{ transition: "opacity .15s" }}
              >
                {/* A full-height hit area: the bar itself is too small a target. */}
                <rect x={x - GAP / 2} y={0} width={BAR_W + GAP} height={H} fill="transparent" />

                {point.failed > 0 && (
                  <rect
                    x={x}
                    y={H - 18 - failH}
                    width={BAR_W}
                    height={Math.max(failH, 2)}
                    rx={RADIUS}
                    className="fill-destructive"
                  />
                )}
                {point.passed > 0 && (
                  <rect
                    x={x}
                    y={H - 18 - failH - (failH ? SEGMENT_GAP : 0) - passH}
                    width={BAR_W}
                    height={Math.max(passH, 2)}
                    // Only the top of the stack gets the rounded data-end.
                    rx={point.failed > 0 ? 2 : RADIUS}
                    className="fill-success"
                  />
                )}

                {/* Direct label — the secondary encoding the colour pair needs. */}
                <text
                  x={x + BAR_W / 2}
                  y={H - 4}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px]"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {point.passed}/{total}
                </text>
              </g>
            );
          })}
        </svg>

        {active && (
          <div className="pointer-events-none absolute -top-1 left-0 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs shadow-md">
            <span className="font-medium">{active.label}</span>
            <span className="tabular ml-2 text-success">{active.passed} passed</span>
            {active.failed > 0 && (
              <span className="tabular ml-2 text-destructive">
                {active.failed} failed
              </span>
            )}
          </div>
        )}
      </div>

      {/* Always present for two series, and labelled — identity never rests on
          hue alone. */}
      <figcaption className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-success" />
          Passed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-destructive" />
          Failed
        </span>
        <span className="ml-auto">last {points.length} runs</span>
      </figcaption>
    </figure>
  );
}
