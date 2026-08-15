import { getSeverityClass } from "../utils/format";

function SeverityBadge({ severity, children }) {
  return (
    <span className={`severity-badge ${getSeverityClass(severity)}`}>
      {children}
    </span>
  );
}

export default SeverityBadge;
