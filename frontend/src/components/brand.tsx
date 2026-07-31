import { Radar } from "lucide-react";

/** The product mark, for screens that sit outside the app shell.
 *
 *  Sign-in and sign-up have no sidebar, so without this they are an anonymous
 *  card floating on grey — the one screen where saying which product this is
 *  actually matters.
 */
export function Brand() {
  return (
    <div className="mb-6 flex flex-col items-center gap-3">
      <span className="brand-gradient lit-lg flex size-12 items-center justify-center rounded-xl text-white">
        <Radar className="size-6" />
      </span>
      <span className="text-center">
        <span className="brand-text block text-xl font-semibold tracking-tight">AutoQA</span>
        <span className="block text-[13px] text-muted-foreground">
          Test automation without writing code
        </span>
      </span>
    </div>
  );
}
