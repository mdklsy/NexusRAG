import { Badge, Layout as AntLayout, Menu, Button, Space, Typography } from "antd";
import {
  AppstoreOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  LogoutOutlined,
  DashboardOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../stores/auth";

export default function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const { email, role, logout } = useAuth();
  if (!useAuth.getState().token) {
    nav("/login");
  }
  // 人机协作全局待办角标（审批 + 审核），值班高频入口
  const { data: hitlCounts } = useQuery({
    queryKey: ["hitl-counts"],
    queryFn: () => api.get<{ approvals: number; reviews: number }>("/api/v1/hitl/counts"),
    refetchInterval: 20000,
  });
  const hitlTotal = (hitlCounts?.approvals || 0) + (hitlCounts?.reviews || 0);

  const items = [
    { key: "/apps", icon: <AppstoreOutlined />, label: "应用" },
    { key: "/kbs", icon: <DatabaseOutlined />, label: "知识库" },
    { key: "/playground", icon: <ExperimentOutlined />, label: "调试" },
    { key: "/evals", icon: <ExperimentOutlined />, label: "评测" },
    {
      key: "/hitl",
      icon: <SafetyCertificateOutlined />,
      // Badge 不包文字：包裹子元素会截断暗色菜单的颜色继承，导致文字变深色不可读
      label: (
        <span>
          人机协作
          {hitlTotal > 0 && <Badge count={hitlTotal} size="small" style={{ marginLeft: 10 }} />}
        </span>
      ),
    },
    { key: "/dashboard", icon: <DashboardOutlined />, label: "看板" },
    ...(role === "admin"
      ? [
          { key: "/users", icon: <TeamOutlined />, label: "用户" },
          { key: "/settings", icon: <SettingOutlined />, label: "设置" },
        ]
      : []),
  ];

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
          items={items}
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
