import AnimatedNumber from "./hud/AnimatedNumber";

function StatusCard({ label, value, detail }) {
  return (
    <div className="status-card">
      <p>{label}</p>
      <h3>{typeof value === "number" ? <AnimatedNumber value={value} format={(v) => Math.round(v)} /> : value}</h3>
      <span>{detail}</span>
    </div>
  );
}

export default StatusCard;
