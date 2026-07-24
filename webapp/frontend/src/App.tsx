import { Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { CaseHomePage } from "./pages/CaseHomePage";
import { CaseLayout } from "./pages/CaseLayout";
import { CasesListPage } from "./pages/CasesListPage";
import { JobProgressPage } from "./pages/JobProgressPage";
import { ParserViewPage } from "./pages/ParserViewPage";
import { UnparsedPage } from "./pages/UnparsedPage";
import { UploadPage } from "./pages/UploadPage";

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<CasesListPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/jobs/:jobId" element={<JobProgressPage />} />
        <Route path="/cases/:caseId" element={<CaseLayout />}>
          <Route index element={<CaseHomePage />} />
          <Route path="m/:moduleName" element={<ParserViewPage />} />
          <Route path="unparsed" element={<UnparsedPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
