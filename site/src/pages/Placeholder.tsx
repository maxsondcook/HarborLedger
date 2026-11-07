export default function Placeholder({ title, week }: { title: string; week?: number }) {
  return (
    <>
      <h1>{title}</h1>
      <p className="lede">{week ? `This view is planned for week ${week} of the build.` : "There is no page at this address."}</p>
    </>
  );
}
