import { Navigate, Outlet, useLocation } from "react-router";
import { getCurrentUser, isAuthenticated } from "../auth";

export function ProtectedRoute() {
  const location = useLocation();

  if (!isAuthenticated()) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}${location.hash}` }}
      />
    );
  }

  return <Outlet />;
}
