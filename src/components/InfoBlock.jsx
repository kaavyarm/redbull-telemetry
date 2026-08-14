function InfoBlock({ title, value }) {
  return (
    <div className="info-block">
      <p>{title}</p>
      <strong>{value}</strong>
    </div>
  );
}

export default InfoBlock;
