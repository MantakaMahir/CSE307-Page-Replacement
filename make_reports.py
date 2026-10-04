"""Render charts and compact, editable reports directly from saved CSV data."""
import csv
import json
import statistics as stats
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage, ImageDraw
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak


def load(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def chart(path, title, labels, series, ylabel):
    image = PILImage.new('RGB', (1100, 650), 'white')
    draw = ImageDraw.Draw(image)
    palette = ['#315b8a', '#b86b24', '#478066', '#944d79']
    draw.text((60, 22), title, fill='black', font_size=28)
    draw.text((60, 64), ylabel, fill='black', font_size=20)
    maximum = 100 if ylabel == 'Hit ratio (%)' else max(v for _, values in series for v in values) * 1.15 or 1
    for tick in range(6):
        y = 510 - tick * 75
        draw.line((95, y, 1050, y), fill='#dddddd')
        draw.text((8, y-10), f'{maximum*tick/5:.2f}', fill='black', font_size=18)
    group = 930 / len(labels)
    width = min(80, group / (len(series) + 1))
    for j, (name, values) in enumerate(series):
        for i, value in enumerate(values):
            x = 100 + i*group + j*width
            draw.rectangle((x, 510-value/maximum*375, x+width-6, 510), fill=palette[j])
        draw.rectangle((70+j*245, 590, 87+j*245, 607), fill=palette[j])
        draw.text((95+j*245, 587), name, fill='black', font_size=19)
    for i, label in enumerate(labels):
        draw.text((100+i*group, 530), label, fill='black', font_size=19)
    image.save(path)


def pdf(path, title, pages):
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 10
    styles['BodyText'].leading = 14
    story = []
    for index, sections in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(escape(title if index == 0 else title + ' (continued)'), styles['Title']))
        for heading, body in sections:
            story.append(Paragraph(escape(heading), styles['Heading2']))
            if isinstance(body, list):
                table = Table(body, hAlign='LEFT', repeatRows=1)
                table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e6edf3')),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,-1),9),
                    ('BOTTOMPADDING',(0,0),(-1,-1),7), ('GRID',(0,0),(-1,-1),0.3,colors.grey)]))
                story.append(table)
            elif isinstance(body, Path):
                story.append(Image(str(body), width=470, height=278))
            else:
                story.append(Paragraph(escape(body).replace('\n', '<br/>'), styles['BodyText']))
            story.append(Spacer(1, 8))
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(45, 25, 'CSE307 | Original implementation | AI assistance disclosed - author reviewed')
        canvas.drawRightString(550, 25, str(document.page))
    SimpleDocTemplate(str(path), rightMargin=45, leftMargin=45, topMargin=40, bottomMargin=45).build(story, onFirstPage=footer, onLaterPages=footer)
    markdown = '# ' + title + '\n\n'
    for sections in pages:
        for heading, body in sections:
            markdown += '## ' + heading + '\n\n'
            if isinstance(body, list):
                markdown += '| ' + ' | '.join(body[0]) + ' |\n'
                markdown += '| ' + ' | '.join('---' for _ in body[0]) + ' |\n'
                markdown += '\n'.join('| ' + ' | '.join(row) + ' |' for row in body[1:]) + '\n\n'
            elif isinstance(body, Path):
                markdown += f'![{heading}]({body.name})\n\n'
            else:
                markdown += body + '\n\n'
    path.with_suffix('.md').write_text(markdown.rstrip() + '\n', encoding='utf-8')


def build(output, include_windows=True):
    rows = load(output / 'simulation.csv')
    metadata = json.loads((output / 'metadata.json').read_text(encoding='utf-8'))
    policies = ['FIFO', 'LRU', 'Optimal', 'Learned']
    def values(policy, phase, frames=6, field='hit_ratio'):
        return [float(r[field]) for r in rows if r['policy']==policy and r['phase']==phase and int(r['frames'])==frames]
    table = [['Policy', 'Before faults', 'After faults', 'Before hit %', 'After hit %']]
    for policy in policies:
        table.append([policy, f"{stats.mean(values(policy,'before',field='faults')):.1f}",
                      f"{stats.mean(values(policy,'after',field='faults')):.1f}",
                      f"{100*stats.mean(values(policy,'before')):.2f}", f"{100*stats.mean(values(policy,'after')):.2f}"])
    chart(output/'policy_hit_ratio.png', 'Workload shift: six frames, mean of five seeds', ['Before shift','After shift'],
          [(p, [100*stats.mean(values(p,phase)) for phase in ['before','after']]) for p in policies], 'Hit ratio (%)')
    chart(output/'frame_sensitivity.png', 'Frame sensitivity: overall mean of five seeds', ['4 frames','6 frames','8 frames'],
          [(p, [100*stats.mean(values(p,'overall',frames)) for frames in [4,6,8]]) for p in policies], 'Hit ratio (%)')
    drops = {p: 100*(stats.mean(values(p,'before'))-stats.mean(values(p,'after'))) for p in policies}
    worst = max(drops, key=drops.get)
    summary = ('With six frames, '+worst+f" had the greatest hit-ratio drop ({drops[worst]:.2f} percentage points). "
               f"The learned policy changed from {100*stats.mean(values('Learned','before')):.2f}% to "
               f"{100*stats.mean(values('Learned','after')):.2f}%. These are measured outcomes, not a guarantee of learned-policy superiority.")
    learned_vs_lru = 100*(stats.mean(values('Learned','overall'))-stats.mean(values('LRU','overall')))
    analysis = (f"The learned policy's overall hit ratio was {learned_vs_lru:+.2f} percentage points relative to LRU at six frames. "
                'The first phase concentrates requests on four pages, so retaining recent hot pages is useful. '
                'After the shift, a larger effective working set and less predictable reuse weaken recency and frequency as predictors. '
                'Optimal still has privileged future information. A large percentage-point drop can reflect a particularly strong first phase, '
                'rather than the worst absolute second-phase performance. The tree is fixed after training: its inputs change online, but its rules do not.')
    references = ('[1] CSE307 Term Paper Brief (Part-B), Track 1, supplied course document.\n'
                  '[2] Arpaci-Dusseau & Arpaci-Dusseau, Operating Systems: Three Easy Pieces, chapter 22: Beyond Physical Memory: Policies. https://pages.cs.wisc.edu/~remzi/OSTEP/\n'
                  '[3] scikit-learn, Decision Trees. https://scikit-learn.org/stable/modules/tree.html')
    sim_pages = [
        [('Problem and hypothesis', 'A limited page cache must choose a victim on a miss. We compare FIFO, LRU, offline Optimal, and a learned reuse classifier under an abrupt access-pattern shift [1,2]. The hypothesis is that localized accesses are easier to cache than random/bursty accesses; learned prediction may or may not improve on LRU.'),
         ('Implementation', 'FIFO removes the earliest insertion, without refreshing on a hit. LRU removes the least recently referenced page. Optimal removes the page used farthest in the future, or never again. All policies begin empty and retain cache contents at the phase boundary. The independent correctness check includes a textbook string, Belady\'s FIFO anomaly, and 729 traces checked against exhaustive minimum-fault search.'),
         ('Learned component', f"A depth-4 decision tree with minimum leaf size 40 is trained on {metadata['simulation']['training_samples']} candidate samples [3]. Features are references since last use and count in the previous 32 references. The binary label is no reuse in the next 12 references, collected from LRU-managed training caches. At a miss the highest predicted non-reuse probability is evicted; ties use oldest access then smaller page ID. The tree is inspectable in tree.txt. This predicts short-horizon non-reuse, not exact Belady victims."),
         ('Experimental setup', 'Four independent training seeds (101-104) and five held-out evaluation seeds (11,22,33,44,55) are used. Each trace has 2400 references to 24 page IDs. Before index 1200, 92% of requests follow a four-page cyclic loop and the rest are random. Afterwards, 65% are uniform random and 35% use a moving three-page burst set. We evaluate 4, 6, and 8 frames. Training traces never contain evaluation references. Future information is used only for training labels and the offline Optimal baseline.')],
        [('Results at six frames', table), ('Hit ratios before and after the shift', output/'policy_hit_ratio.png'),
         ('Observed change', summary), ('Measurement', 'Each phase has 1200 references. Hit ratio equals 1 minus faults divided by references. The table reports means across five seeds; simulation.csv retains every seed and frame count. windows.csv stores 100-reference fault-rate bins for one illustrative trace. Counts are simulator misses, not Windows OS page-fault counters.')],
        [('Analysis', analysis), ('Frame-count sensitivity', output/'frame_sensitivity.png'),
         ('Limitations and conclusion', 'The workload is synthetic, the classifier sees only two historical features, and training candidates come from LRU rather than the learned policy\'s own occupancy. This state-distribution mismatch and the fixed prediction horizon can limit generalization. We do not model dirty writes, disk latency or OS overhead. Five seeds describe this generator, not all workloads. The defensible conclusion is that workload shifts affect every policy; future-aware Optimal supplies a lower bound and learned eviction must be evaluated rather than presumed better.'),
         ('References and disclosure', references+'\nAI assistance supported implementation, report drafting and local experiment execution. The author reviewed the code, saved results, and report analysis.')]
    ]
    pdf(output/'algorithm_report.pdf', 'Page Replacement Under a Workload Shift', sim_pages)
    if include_windows:
        resource_rows = load(output/'windows_resources.csv')
        groups = {}
        for row in resource_rows:
            key = (row['kind'], int(row['working_set_limit_mib']), int(row['allowed_cpus']))
            groups.setdefault(key, []).append(row)
        resource_table = [['Condition', 'Median wall s', 'Range s', 'Median faults', 'Sampled RSS MiB']]
        medians = []
        for key in [('memory',24,1),('memory',96,1),('cpu',0,1),('cpu',0,2)]:
            samples = groups[key]
            times = [float(r['wall_seconds']) for r in samples]
            medians.append(stats.median(times))
            resource_table.append([f'{key[1]} MiB' if key[0]=='memory' else f'{key[2]} logical CPU(s)',
                f'{stats.median(times):.3f}', f'{min(times):.3f}-{max(times):.3f}',
                f"{stats.median(float(r['windows_fault_delta']) for r in samples):.0f}",
                f"{stats.median(float(r['sampled_rss_mib']) for r in samples):.2f}"])
        chart(output/'resource_runtime.png', 'Windows controlled resource experiments: three repetitions', ['24 MiB','96 MiB','1 CPU','2 CPUs'], [('Wall time',medians)], 'Median elapsed time (s)')
        win = metadata['windows']
        resource_refs = ('[4] Microsoft, Working Set. https://learn.microsoft.com/en-us/windows/win32/memory/working-set\n'
                         '[5] Microsoft, SetProcessWorkingSetSizeEx. https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-setprocessworkingsetsizeex\n'
                         '[6] psutil documentation. https://psutil.readthedocs.io/\nAll web references accessed during project generation on '+metadata['created_utc'][:10]+'.')
        resource_pages = [
            [('Research question', 'How does the same bounded workload behave when available residency or CPU scheduling resources change? This Windows experiment complements the simulated page-replacement study with real process measurements. No classifier or trained model is used in these resource workloads.'),
             ('Windows adaptation', 'The resource experiment uses Windows processes rather than Ubuntu guests. A hard maximum working-set limit controls resident pageable memory [4,5]; it does not cap committed virtual memory or emulate a VM RAM allocation. CPU affinity restricts workers to one or two allowed logical CPUs [6]; it is not a VMware virtual-CPU configuration. These substitutions permit controlled local measurements but do not establish Ubuntu/VMware behavior.'),
             ('Environment', f"Python {metadata['python']}; Windows; {win['cpu_model']}; {win['logical_cpus']} logical CPUs; {win['total_ram_mib']:.0f} MiB installed RAM. The first two allowed logical CPU IDs are {win['allowed_cpus'][:2]}. Exact dependency versions and run time are in metadata.json."),
             ('OS background', 'Resident working-set pages can be accessed without a residency fault. A fault may be soft, resolved from RAM, or hard, requiring backing-store I/O [4]. A restricted process can fault repeatedly even when the whole machine has ample free RAM. Thus total process page faults alone are not proof of disk swapping or system-wide thrashing.')],
            [('Memory workload', 'A fresh child sets a 24 MiB or 96 MiB maximum working set using SetProcessWorkingSetSizeEx with HARDWS_MAX_ENABLE and HARDWS_MIN_DISABLE. The API return is checked. It allocates 48 MiB, constructs a fixed shuffled list of 4096-byte-spaced offsets, and updates one byte at each offset for eight passes. Both conditions use identical accesses and one CPU. Allocation faults occur before the counter baseline and are excluded; setup and allocation time remain in parent wall time.'),
             ('CPU workload', 'Each condition launches two independent Python processes. Each performs 12000 SHA-256 hashes of a 64 KiB buffer. Both workers are restricted to the same one CPU or same two CPUs. The number of workers and total work stay constant, so elapsed-time differences reflect resource availability plus scheduling and startup effects. Logical CPUs may share a physical core; two logical CPUs do not necessarily double throughput.'),
             ('Protocol and metrics', 'Three repetitions per condition run in a deterministic shuffled order to reduce simple order bias. Each condition uses new processes. Parent wall time includes startup; work_seconds records the slower child\'s measured loop duration. Child CPU times are summed. Page-fault deltas use psutil\'s Windows counter; RSS is sampled after each pass and reported as the maximum sample per child. RSS is not a continuously observed peak. Subprocess timeouts and nonzero exits fail the run.'),
             ('Reproduction', 'From the project folder run python main.py. The run checks the simulator, trains and evaluates it, executes 12 resource conditions, and regenerates tables, charts and reports. Raw observations are saved before report generation. Repeated Windows timings are expected to vary; seeded simulation CSV values should repeat.')],
            [('Measured resource results', resource_table), ('Elapsed-time comparison', output/'resource_runtime.png'),
             ('Memory and CPU comparisons', f"Median end-to-end memory runtime was {medians[0]/medians[1]:.2f} times as high at 24 MiB versus 96 MiB. CPU end-to-end speedup (one-CPU time / two-CPU time) was {medians[2]/medians[3]:.2f}. The table includes ranges because only three repetitions are available. These ratios describe this run and include process startup, not just steady-state throughput."),
             ('Integrity of observations', 'windows_resources.csv contains all 12 observations, checksums and separate child work times. Identical memory checksums should occur in every condition, showing that the same number of updates completed. Total Windows faults include soft and hard faults. No disk-I/O trace was collected, so the measurements cannot isolate hard-fault costs.')],
            [('Connecting simulation and measurement', summary+' The simulation explicitly selects victims, whereas the Windows kernel owns replacement in the resource experiment. We did not install FIFO, LRU or the learned policy in Windows. The experiments share the concept of limited residency, but their page-fault counts have different definitions and cannot be directly compared.'),
             ('Interpretation and limitations', 'A tight residency cap is expected to make revisiting the 48 MiB allocation incur more faults. Removed pages can remain in physical RAM outside the process working set, so increased faults may largely be soft faults [4]. CPU results can depend on physical-core placement, thermal conditions, other applications and scheduler overhead. The workload is deliberately small and synthetic. Working-set samples and three repeats do not justify universal performance claims. Controlled VM experiments would be needed to extend the conclusion to Ubuntu or VMware.'),
             ('Conclusion', 'This project supplies two complementary pieces of evidence: deterministic policy-level behavior under a deliberate trace shift, and real Windows process measurements under bounded resource restrictions. The saved raw observations support local comparisons and make negative or mixed learned-policy results visible. Resource experiments remain independent of training.'),
             ('References and disclosure', references+'\n'+resource_refs+'\nAI assistance supported implementation, report drafting and local experiment execution. The author reviewed the code, saved results, and report analysis. Windows was used as the local substitute for Ubuntu/VMware resource settings; the report explains the differences and limits.')]
        ]
        pdf(output/'windows_report.pdf', 'Windows Memory and CPU Resource Experiments', resource_pages)
    summary_text = summary+'\n\n'+analysis+'\n'
    (output/'summary.txt').write_text(summary_text, encoding='utf-8')
    print(summary_text)


if __name__ == '__main__':
    build(Path(__file__).resolve().parent/'results')
