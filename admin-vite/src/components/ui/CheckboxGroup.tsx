"use client";

interface CheckboxOption {
  value: string;
  label: string;
}

type CheckboxOptionOrString = CheckboxOption | string;

interface CheckboxGroupProps {
  name: string;
  options: readonly CheckboxOptionOrString[];
  value: string[];
  onChange: (value: string, checked: boolean) => void;
  columns?: 1 | 2 | 3 | 4;
  className?: string;
}

function getOptionValue(opt: CheckboxOptionOrString): string {
  return typeof opt === "string" ? opt : opt.value;
}

function getOptionLabel(opt: CheckboxOptionOrString): string {
  return typeof opt === "string" ? opt : opt.label;
}

export function CheckboxGroup({ name, options, value, onChange, columns = 2, className = "" }: CheckboxGroupProps) {
  return (
    <fieldset className={`checkbox-group checkbox-group-${columns} ${className}`}>
      <legend className="visually-hidden">{name}</legend>
      {options.map(opt => {
        const optValue = getOptionValue(opt);
        const optLabel = getOptionLabel(opt);
        return (
          <label key={optValue} className="checkbox-item">
            <input
              type="checkbox"
              name={name}
              value={optValue}
              checked={value.includes(optValue)}
              onChange={e => onChange(optValue, e.target.checked)}
              className="checkbox-input"
            />
            <span className="checkbox-check" aria-hidden="true" />
            <span className="checkbox-label">{optLabel}</span>
          </label>
        );
      })}
    </fieldset>
  );
}