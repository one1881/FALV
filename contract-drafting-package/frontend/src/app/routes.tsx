import { createBrowserRouter, Navigate } from "react-router";
import Layout from "./Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Login } from "./pages/Login";
import { ContractManage } from "./pages/ContractManage";
import { DraftingCenter } from "./pages/DraftingCenter";
import { Approvals } from "./pages/Approvals";
import { ContractReview } from "./pages/ContractReview";
import { ReviewManagement } from "./pages/ReviewManagement";
import { ContractEditor } from "./pages/ContractEditor";
import { LitigationNew } from "./pages/LitigationNew";
import { LitigationEvidence } from "./pages/LitigationEvidence";

export const router = createBrowserRouter([
  { path: "/login", Component: Login },
  {
    Component: ProtectedRoute,
    children: [
      {
        path: "/",
        Component: Layout,
        children: [
          { index: true, element: <Navigate to="/litigation/new" replace /> },
          { path: "drafting", Component: DraftingCenter },
          { path: "drafting/contracts", Component: ContractManage },
          { path: "drafting/editor/:id", Component: ContractEditor },
          { path: "approvals", Component: Approvals },
          { path: "review/result", Component: ContractReview },
          { path: "review-management", Component: ReviewManagement },
          { path: "litigation/new", Component: LitigationNew },
          { path: "litigation/evidence", Component: LitigationEvidence },
          { path: "*", element: <Navigate to="/litigation/new" replace /> },
        ],
      },
    ],
  },
]);
