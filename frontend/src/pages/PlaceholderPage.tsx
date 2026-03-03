import { Card, Typography } from "antd";

const { Text } = Typography;

interface PlaceholderPageProps {
  title: string;
}

function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <Card title={title}>
      <Text type="secondary">该页面为占位页，可在下一阶段接入真实功能。</Text>
    </Card>
  );
}

export default PlaceholderPage;
