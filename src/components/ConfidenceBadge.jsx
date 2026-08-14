import { getConfidenceClass } from "../utils/format";

function ConfidenceBadge({ confidence, children }) {
  return (
    <span className={`confidence ${getConfidenceClass(confidence)}`}>
      {children}
    </span>
  );
}

export default ConfidenceBadge;
