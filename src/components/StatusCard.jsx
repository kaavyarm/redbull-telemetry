function StatusCard({ label, value, detail }) {
  return (
    <div className="status-card">
      <p>{label}</p>
      <h3>{value}</h3>
      <span>{detail}</span>
    </div>
  );
}

export default StatusCard;
