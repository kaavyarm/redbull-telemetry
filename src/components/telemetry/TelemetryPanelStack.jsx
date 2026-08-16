import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { TELEMETRY_CHANNELS } from "../../utils/telemetryChannels";

// Stacks one thin Recharts LineChart per channel, all sharing one syncId so
// Recharts' own synced-cursor/tooltip behavior (a real feature since v2,
// unchanged in the 3.x here) ties them together for free -- no custom
// cursor state, no new charting dependency. Only the bottom panel renders a
// visible XAxis; the rest render a same-height hidden one so every panel's
// plot area lines up exactly (syncId only aligns charts whose axes match).
function TelemetryPanelStack({ series, syncId, compareMode = false, onHover }) {
  return (
    <div className="telemetry-stack">
      {TELEMETRY_CHANNELS.map((channel, index) => {
        const isLast = index === TELEMETRY_CHANNELS.length - 1;
        const lineType = channel.kind === "step" ? "stepAfter" : "monotone";

        return (
          <div className="telemetry-panel" key={channel.key}>
            <span className="telemetry-panel-label">
              {channel.label}
              {channel.unit ? ` (${channel.unit})` : ""}
            </span>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={series}
                syncId={syncId}
                margin={{ top: 6, right: 12, bottom: 0, left: 0 }}
                onMouseMove={(state) => onHover?.(state?.activeLabel ?? null)}
                onMouseLeave={() => onHover?.(null)}
              >
                <XAxis
                  dataKey="timeS"
                  stroke="var(--muted)"
                  fontSize={11}
                  tickFormatter={(v) => v.toFixed(0)}
                  hide={!isLast}
                  height={isLast ? 22 : 0}
                />
                <YAxis domain={channel.domain} hide width={0} />
                <Tooltip contentStyle={{ background: "#0a0b0d", border: "1px solid var(--border)" }} />
                {compareMode ? (
                  <>
                    <Line
                      type={lineType}
                      dataKey={`a${channel.key[0].toUpperCase()}${channel.key.slice(1)}`}
                      stroke="var(--blue-bright)"
                      dot={false}
                      strokeWidth={1.5}
                      isAnimationActive={false}
                    />
                    <Line
                      type={lineType}
                      dataKey={`b${channel.key[0].toUpperCase()}${channel.key.slice(1)}`}
                      stroke="var(--amber)"
                      dot={false}
                      strokeWidth={1.5}
                      isAnimationActive={false}
                    />
                  </>
                ) : (
                  <Line
                    type={lineType}
                    dataKey={channel.key}
                    stroke={channel.color}
                    dot={false}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </div>
  );
}

export default TelemetryPanelStack;
