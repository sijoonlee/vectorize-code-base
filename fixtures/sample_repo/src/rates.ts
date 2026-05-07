export function validateMortgageRate(rate: number): boolean {
  return rate > 0 && rate < 100;
}

export class RateFormatter {
  formatPercent(rate: number): string {
    return `${rate.toFixed(2)}%`;
  }
}
