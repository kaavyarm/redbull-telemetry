// Standard Blob + object-URL download -- nothing like this existed
// anywhere in the app before, and it's a small enough need that a library
// would be overkill.
function escapeCsvCell(value) {
  if (value === null || value === undefined) return "";
  const str = String(value);
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

// columns: [{ key, label }] -- key indexes into each row (plain object or
// via an accessor function), label is the CSV header text.
export function downloadCsv(filename, rows, columns) {
  const header = columns.map((c) => escapeCsvCell(c.label)).join(",");
  const body = rows
    .map((row) =>
      columns
        .map((c) => escapeCsvCell(typeof c.key === "function" ? c.key(row) : row[c.key]))
        .join(",")
    )
    .join("\n");
  const csv = `${header}\n${body}`;

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
