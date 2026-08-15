import { downloadCsv } from "../utils/csv";

// One button, reused next to every dense table's heading -- rows/columns
// are passed in already shaped for that specific table (no attempt to
// infer columns from arbitrary row objects).
function ExportButton({ filename, rows, columns }) {
  return (
    <button
      className="secondary-button"
      onClick={() => downloadCsv(filename, rows, columns)}
      disabled={!rows?.length}
    >
      Export CSV
    </button>
  );
}

export default ExportButton;
