import { getCompoundClass } from "../utils/format";

function CompoundBadge({ compound }) {
  if (!compound) return <span className="compound-badge unknown">—</span>;
  return <span className={`compound-badge ${getCompoundClass(compound)}`}>{compound}</span>;
}

export default CompoundBadge;
