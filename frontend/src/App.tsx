import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { Toaster as ShadToaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import TestPage from "./pages/TestPage";
import AdminPage from "./pages/AdminPage";
import TestPagePreview from "./pages/TestPagePreview";
import IncomingInspectionPage from "./pages/IncomingInspectionPage";
import NotFound from "./pages/NotFound";
import { DeploymentGate, StationBadge, UpdateBanner } from "./components/DeploymentGate";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter>
         <DeploymentGate>
          <div className="app-shell grid-bg">
            <UpdateBanner />
            <header className="border-b bg-card/80 backdrop-blur">
              <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center gap-4 justify-between">
                <div className="flex items-center gap-3">
                  <img src="/logo.png" alt="smarton logo" className="w-10 h-10 rounded-lg object-cover" />
                  <div>
                    <div className="text-lg font-semibold text-foreground">smarton 测试系统</div>
                    <StationBadge />
                  </div>
                </div>
                <nav className="flex items-center gap-2 text-sm">
                  <NavLink
                    to="/"
                    end
                    className={({ isActive }) =>
                      `px-4 py-2 rounded-full border transition ${isActive ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:text-foreground"}`
                    }
                  >
                    测试
                  </NavLink>
                  <NavLink
                    to="/inspection"
                    className={({ isActive }) =>
                      `px-4 py-2 rounded-full border transition ${isActive ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:text-foreground"}`
                    }
                  >
                    入料检验
                  </NavLink>
                  <NavLink
                    to="/admin"
                    className={({ isActive }) =>
                      `px-4 py-2 rounded-full border transition ${isActive ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:text-foreground"}`
                    }
                  >
                    管理
                  </NavLink>
                </nav>
              </div>
            </header>
            <main className="max-w-6xl mx-auto py-8 px-6">
              <Routes>
                <Route path="/" element={<TestPage />} />
                <Route path="/inspection" element={<IncomingInspectionPage />} />
                <Route path="/admin" element={<AdminPage />} />
                <Route path="/test-preview" element={<TestPagePreview />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </main>
          </div>
         </DeploymentGate>
          <Toaster />
          <ShadToaster />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
