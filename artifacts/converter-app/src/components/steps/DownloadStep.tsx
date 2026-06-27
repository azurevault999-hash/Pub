import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  useGetConversion,
  getGetConversionQueryKey,
} from "@workspace/api-client-react";
import {
  Download, FileText, RefreshCw, CheckCircle2,
  FileCode, ScrollText, Globe,
} from "lucide-react";

interface DownloadStepProps {
  sessionId: string;
  onReset: () => void;
}

const FILE_META: Record<string, {
  icon: React.ElementType;
  title: string;
  description: string;
  badge: string;
  badgeVariant: "default" | "secondary" | "destructive" | "outline";
}> = {
  "woocommerce_products.csv": {
    icon: FileCode,
    title: "WooCommerce Products CSV",
    description: "Ready-to-import WooCommerce 10.9.1 compatible CSV. Upload directly via WooCommerce → Products → Import.",
    badge: "Primary Output",
    badgeVariant: "default",
  },
  "migration_report.txt": {
    icon: ScrollText,
    title: "Migration Report",
    description: "Full summary of the migration: products, variants, images, categories, tags, warnings, errors, and timing statistics.",
    badge: "Report",
    badgeVariant: "secondary",
  },
  "validation_report.html": {
    icon: Globe,
    title: "Validation Report",
    description: "Interactive HTML report with all validation results (ERROR / WARN / INFO / PASS) — searchable and filterable.",
    badge: "HTML",
    badgeVariant: "secondary",
  },
  "conversion_log.txt": {
    icon: FileText,
    title: "Conversion Log",
    description: "Timestamped log of every step taken during conversion, including warnings and any errors.",
    badge: "Log",
    badgeVariant: "outline",
  },
};

export function DownloadStep({ sessionId, onReset }: DownloadStepProps) {
  const { data: conversionData } = useGetConversion(
    sessionId,
    { query: { enabled: !!sessionId, queryKey: getGetConversionQueryKey(sessionId) } }
  );

  const base = import.meta.env.BASE_URL.replace(/\/$/, "");

  const buildDownloadUrl = (filename: string) =>
    `${base}/api/sessions/${sessionId}/download/${filename}`;

  const files = conversionData?.output_files ?? [];

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight mb-1">Downloads</h2>
          <p className="text-muted-foreground text-sm">
            Your converted files are ready. Download and import into WooCommerce.
          </p>
        </div>
        {conversionData && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
            <CheckCircle2 className="w-4 h-4 text-green-500" />
            <span>{conversionData.products_converted} products converted</span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4">
        {files.map((filename) => {
          const meta = FILE_META[filename] ?? {
            icon: FileText,
            title: filename,
            description: "Generated output file.",
            badge: "File",
            badgeVariant: "secondary" as const,
          };
          const Icon = meta.icon;

          return (
            <Card key={filename} className="transition-colors hover:border-primary/40">
              <CardContent className="flex items-center gap-4 p-5">
                <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center shrink-0">
                  <Icon className="w-6 h-6 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <p className="font-semibold text-sm">{meta.title}</p>
                    <Badge variant={meta.badgeVariant as any} className="text-xs">{meta.badge}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{meta.description}</p>
                  <p className="font-mono text-xs text-muted-foreground/60 mt-1">{filename}</p>
                </div>
                <a
                  href={buildDownloadUrl(filename)}
                  download={filename}
                  data-testid={`button-download-${filename}`}
                >
                  <Button variant="outline" size="sm" className="shrink-0 gap-2">
                    <Download className="w-4 h-4" />
                    Download
                  </Button>
                </a>
              </CardContent>
            </Card>
          );
        })}

        {files.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center py-12 text-center">
              <Download className="w-10 h-10 text-muted-foreground/30 mb-3" />
              <p className="text-muted-foreground text-sm">No files available yet.</p>
            </CardContent>
          </Card>
        )}
      </div>

      <Separator />

      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground space-y-1">
          <p>Import the WooCommerce CSV via <span className="font-mono">Products → Import</span> in your WordPress admin.</p>
          <p>Images are preserved as Shopify CDN URLs — WooCommerce will fetch them during import.</p>
        </div>
        <Button variant="outline" onClick={onReset} size="sm" className="shrink-0 ml-4" data-testid="button-new-conversion">
          <RefreshCw className="w-4 h-4 mr-2" />
          New Conversion
        </Button>
      </div>
    </div>
  );
}
