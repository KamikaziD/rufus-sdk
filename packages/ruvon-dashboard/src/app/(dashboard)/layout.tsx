import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { headers } from "next/headers";
import { Sidebar } from "@/components/layouts/Sidebar";
import { Topbar } from "@/components/layouts/Topbar";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const headersList = headers();
  const testBypass =
    process.env.PLAYWRIGHT_TEST_BYPASS === "true" &&
    headersList.get("x-test-bypass") === "true";

  const session = testBypass ? null : await auth();

  if (!testBypass && !session) {
    redirect("/login");
  }

  return (
    <div className="min-h-screen bg-[#0A0A0B]">
      <Sidebar />
      <Topbar />
      <main className="pl-56 pt-14">
        <div className="p-6">{children}</div>
      </main>
    </div>
  );
}
