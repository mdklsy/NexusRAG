import { Layout as AntLayout, Menu, Button, Space, Typography } from "antd";
import {
  AppstoreOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  LogoutOutlined,
  DashboardOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../stores/auth";

const ITEMS = [
  { key: "/apps", icon: <AppstoreOutlined />, label: "应用" },
  { key: "/kbs", icon: <DatabaseOutlined />, label: "知识库" },
  { key: "/playground", icon: <ExperimentOutlined />, label: "调试" },
  { key: "/dashboard", icon: <DashboardOutlined />, label: "看板" },
];

export default function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const { email, logout } = useAuth();
  if (!useAuth.getState().token) {
    nav("/login");
  }

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <AntLayout.Sider theme="dark" width={200}>
        <div
          style={{
            color: "#fff",
            padding: "20px 16px",
            fontSize: 20,
            fontWeight: 700,
            letterSpacing: 1,
          }}
        >
          Nexus<span style={{ color: "#1677ff" }}>RAG</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[loc.pathname.startsWith("/kbs") ? "/kbs" : loc.pathname]}
          items={ITEMS}
          onClick={({ key }) => nav(key)}
        />
        <div style={{ position: "absolute", bottom: 16, left: 0, right: 0, padding: "0 12px" }}>
          <Space>
            <Typography.Text style={{ color: "#888", fontSize: 12 }}>{email}</Typography.Text>
            <Button
              size="small"
              type="text"
              icon={<LogoutOutlined />}
              onClick={() => {
                logout();
                nav("/login");
              }}
            />
          </Space>
        </div>
      </AntLayout.Sider>
      <AntLayout.Content style={{ padding: 20, overflow: "auto", height: "100vh" }}>
        <Outlet />
      </AntLayout.Content>
    </AntLayout>
  );
}
