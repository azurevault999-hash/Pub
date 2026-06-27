import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ArrowRight, Package, Layers, Image, Tag, Store, FolderOpen, AlertTriangle, CheckCircle2, XCircle, HelpCircle } from "lucide-react";
import type { AnalysisResult } from "@workspace/api-client-react";

interface AnalysisStepProps {
  sessionId: string;
  initialData: AnalysisResult;
  onNext: () => void;
}

function StatCard({ icon: Icon, label, value, variant = "default" }: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  variant?: "default" | "warning" | "success" | "error";
}) {
  const variantClasses = {
    default: "border-border bg-card",
    warning: "border-yellow-500/30 bg-yellow-500/5",
    success: "border-green-500/30 bg-green-500/5",
    error: "border-red-500/30 bg-red-500/5",
  };
  const iconClasses = {
    default: "text-primary",
    warning: "text-yellow-500",
    success: "text-green-500",
    error: "text-red-500",
  };

  return (
    <div className={`rounded-lg border p-4 flex items-start gap-3 transition-colors ${variantClasses[variant]}`}>
      <div className={`mt-0.5 ${iconClasses[variant]}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">{label}</p>
        <p className="text-2xl font-bold mt-0.5 tabular-nums">{value}</p>
      </div>
    </div>
  );
}

function ListSection({ title, items, emptyMessage }: { title: string; items: string[]; emptyMessage: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-2">{title}</p>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">{emptyMessage}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <Badge key={item} variant="secondary" className="text-xs font-normal">{item}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export function AnalysisStep({ sessionId, initialData: data, onNext }: AnalysisStepProps) {
  const issues = [
    { label: "Duplicate SKUs", value: data.duplicate_skus, icon: AlertTriangle, isBad: data.duplicate_skus > 0 },
    { label: "Missing Prices", value: data.missing_prices, icon: AlertTriangle, isBad: data.missing_prices > 0 },
    { label: "Missing Images", value: data.missing_images, icon: AlertTriangle, isBad: data.missing_images > 0 },
    { label: "Invalid HTML blocks", value: data.invalid_html_count, icon: AlertTriangle, isBad: data.invalid_html_count > 0 },
    { label: "Unknown columns", value: data.unknown_columns.length, icon: HelpCircle, isBad: data.unknown_columns.length > 0 },
  ];

  const hasIssues = issues.some((i) => i.isBad);

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div>
        <h2 className="text-2xl font-bold tracking-tight mb-1">File Analysis</h2>
        <p className="text-muted-foreground text-sm">
          Analysed <span className="font-mono text-foreground">{data.total_rows}</span> rows.
          Review the findings below before proceeding to validation.
        </p>
      </div>

      {/* Primary stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <StatCard icon={Package} label="Products" value={data.product_count} variant="success" />
        <StatCard icon={Layers} label="Variants" value={data.variant_count} />
        <StatCard icon={Image} label="Images" value={data.image_count} />
      </div>

      {/* Metadata */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Metadata</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ListSection title="Categories / Types" items={data.categories} emptyMessage="No product categories found" />
          <Separator />
          <ListSection title="Vendors" items={data.vendors} emptyMessage="No vendors found" />
          {data.unknown_columns.length > 0 && (
            <>
              <Separator />
              <ListSection title="Unknown Columns (will be ignored)" items={data.unknown_columns} emptyMessage="" />
            </>
          )}
        </CardContent>
      </Card>

      {/* Data quality */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            Data Quality
            {hasIssues
              ? <AlertTriangle className="w-4 h-4 text-yellow-500" />
              : <CheckCircle2 className="w-4 h-4 text-green-500" />
            }
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="divide-y divide-border">
            {issues.map((issue) => (
              <div key={issue.label} className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
                <div className="flex items-center gap-2 text-sm">
                  <issue.icon className={`w-4 h-4 ${issue.isBad ? "text-yellow-500" : "text-muted-foreground"}`} />
                  <span className={issue.isBad ? "text-foreground" : "text-muted-foreground"}>{issue.label}</span>
                </div>
                <Badge
                  variant={issue.isBad ? "destructive" : "secondary"}
                  className={`font-mono text-xs ${!issue.isBad ? "opacity-60" : ""}`}
                >
                  {issue.value}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={onNext} size="lg" data-testid="button-next-validation">
          Continue to Validation
          <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );
}
