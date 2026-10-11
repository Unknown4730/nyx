import { Chip, Panel, SectionHeading, TD, TH, Table, ToneChip } from '@/components/ui'
import { humanise } from '@/lib/format'
import { confidenceTone, PROVIDER_ACCENT } from '@/lib/tone'
import type { AnalysisResult, ServiceMapping } from '@/types/analysis'

function Cell({ mapping }: { mapping: ServiceMapping | null | undefined }) {
  if (!mapping) return <span className="text-silver">No direct equivalent</span>
  return (
    <div className="min-w-[10rem] space-y-1">
      {mapping.service_url ? (
        <a href={mapping.service_url} target="_blank" rel="noopener noreferrer" className="nyx-link font-medium">
          {mapping.service_name}
        </a>
      ) : (
        <span className="font-medium">{mapping.service_name}</span>
      )}
      <div className="flex flex-wrap gap-1">
        <Chip>{humanise(mapping.serverless_class, 'class not stated')}</Chip>
        {mapping.confidence ? <ToneChip tone={confidenceTone(mapping.confidence)}>{`${humanise(mapping.confidence)} fit`}</ToneChip> : null}
      </div>
    </div>
  )
}

export function ServicesPanel({ result }: { result: AnalysisResult }) {
  const notable = (result.mapping_table ?? []).filter((row) => !row.one_to_one)
  return (
    <div className="grid gap-6">
      <Panel labelledBy="services-heading">
        <SectionHeading
          id="services-heading"
          eyebrow="Multi-cloud"
          title="Logical components mapped to each provider"
          description="The same logical component on AWS, Google Cloud and Azure. Mappings come from the NYX service catalogue, which lists services and their serverless class. It is not a pricing file."
        />
        <div className="mt-5">
          <Table caption="Logical component to cloud service mapping">
            <thead>
              <tr>
                <th className={TH}>Logical component</th>
                {(['aws', 'gcp', 'azure'] as const).map((provider) => (
                  <th key={provider} className={TH}>
                    {PROVIDER_ACCENT[provider]?.label}
                  </th>
                ))}
                <th className={TH}>One-to-one</th>
              </tr>
            </thead>
            <tbody>
              {(result.mapping_table ?? []).map((row) => (
                <tr key={row.component_id}>
                  <td className={`${TD} min-w-[9rem] font-medium`}>
                    {row.component_label}
                    <p className="mt-0.5 text-2xs font-normal text-silver">{humanise(row.logical_type)}</p>
                  </td>
                  <td className={TD}>
                    <Cell mapping={row.aws} />
                  </td>
                  <td className={TD}>
                    <Cell mapping={row.gcp} />
                  </td>
                  <td className={TD}>
                    <Cell mapping={row.azure} />
                  </td>
                  <td className={TD}>
                    <Chip>{row.one_to_one ? 'Yes' : 'No'}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Panel>

      <Panel>
        <SectionHeading eyebrow="Equivalence" title="Where the mapping is imperfect" />
        {notable.length === 0 ? (
          <p className="mt-4 text-sm text-silver">Every logical component maps one-to-one in this analysis.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {notable.map((row) => (
              <li key={row.component_id} className="nyx-inset p-4 text-sm">
                <p className="font-medium text-chalk">{row.component_label}</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-silver">
                  {(row.notes ?? []).map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
